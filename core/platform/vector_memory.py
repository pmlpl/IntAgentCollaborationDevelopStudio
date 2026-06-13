# core/platform/vector_memory.py — ChromaDB 向量记忆中台
#
# 在文件/SQLite FTS 基础上增加语义搜索能力。
# 使用 ChromaDB 内嵌 ONNX 嵌入（无需额外安装模型），
# 搜索时优先向量检索 → 关键词召回 RRF 融合排序。
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.logging import get_logger

logger = get_logger(__name__)


class VectorMemoryError(Exception):
    """向量记忆异常。"""


# ── ChromaDB 连接管理 ──

def _get_chroma_client(persist_dir: Path) -> Any:
    """获取或创建 PersistentClient。"""
    import chromadb

    persist_dir.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(persist_dir))


def _get_or_create_collection(client, namespace: str) -> Any:
    """按命名空间获取/创建 collection。ChromaDB collection 名不能含特殊字符。"""
    safe_name = re.sub(r"[^\w\-]", "_", namespace)
    # 确保名字以字母开头
    if safe_name and safe_name[0].isdigit():
        safe_name = "ns_" + safe_name
    if not safe_name:
        safe_name = "default"
    try:
        return client.get_collection(safe_name)
    except Exception:
        # 使用 ChromaDB 内置 ONNX 嵌入（all-MiniLM-L6-v2，~80MB 首次下载）
        try:
            from chromadb.utils import embedding_functions
            ef = embedding_functions.DefaultEmbeddingFunction()
        except Exception:
            ef = None  # 降级：无嵌入函数（ChromaDB 会报错，调用方需处理）
        return client.create_collection(
            safe_name,
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )


# ── CRUD ──

def vector_upsert(
    persist_dir: Path,
    namespace: str,
    key: str,
    text: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> None:
    """写入/更新一条向量记忆。"""
    try:
        client = _get_chroma_client(persist_dir)
        coll = _get_or_create_collection(client, namespace)
        meta = metadata or {}
        meta["updated_at"] = datetime.now(timezone.utc).isoformat()
        meta["key"] = key

        # 删除旧记录（如有）后插入
        try:
            existing = coll.get(ids=[key], include=[])
            if existing and existing.get("ids"):
                coll.delete(ids=[key])
        except Exception:
            pass

        coll.add(
            ids=[key],
            documents=[text],
            metadatas=[meta],
        )
        logger.debug("vector_upsert: %s/%s (%d chars)", namespace, key, len(text))
    except Exception as exc:
        logger.warning("vector_upsert failed for %s/%s: %s", namespace, key, exc)
        raise VectorMemoryError(f"向量写入失败: {exc}") from exc


def vector_search(
    persist_dir: Path,
    namespace: str,
    query: str,
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """向量语义搜索（默认 cosine 距离）。"""
    try:
        client = _get_chroma_client(persist_dir)
        coll = _get_or_create_collection(client, namespace)
    except Exception as exc:
        logger.warning("vector_search: collection access failed: %s", exc)
        return []

    try:
        results = coll.query(
            query_texts=[query],
            n_results=min(limit, 50),
            include=["documents", "metadatas", "distances"],
        )
    except Exception as exc:
        logger.warning("vector_search query failed: %s", exc)
        return []

    if not results or not results.get("ids") or not results["ids"][0]:
        return []

    out: list[dict[str, Any]] = []
    for i, doc_id in enumerate(results["ids"][0]):
        doc = results["documents"][0][i] if results.get("documents") and results["documents"][0] else ""
        meta = results["metadatas"][0][i] if results.get("metadatas") and results["metadatas"][0] else {}
        dist = results["distances"][0][i] if results.get("distances") and results["distances"][0] else 1.0
        # cosine distance → similarity (distance=0 means identical, distance=2 means opposite)
        similarity = max(0.0, 1.0 - float(dist) / 2.0)
        out.append({
            "namespace": namespace,
            "key": doc_id,
            "text": doc,
            "metadata": meta,
            "updated_at": meta.get("updated_at", ""),
            "updated_by": meta.get("updated_by", ""),
            "score": round(similarity, 4),
            "source": "vector",
        })
    return out


def vector_delete(persist_dir: Path, namespace: str, key: str) -> bool:
    """删除一条向量记忆。"""
    try:
        client = _get_chroma_client(persist_dir)
        coll = _get_or_create_collection(client, namespace)
        coll.delete(ids=[key])
        return True
    except Exception as exc:
        logger.warning("vector_delete failed: %s", exc)
        return False


def vector_list_namespaces(persist_dir: Path) -> list[str]:
    """列出有数据的命名空间。"""
    try:
        client = _get_chroma_client(persist_dir)
        collections = client.list_collections()
        return sorted(c.name for c in collections if c.count() > 0)
    except Exception as exc:
        logger.warning("vector_list_namespaces failed: %s", exc)
        return []


def vector_count(persist_dir: Path, namespace: str) -> int:
    """返回命名空间中的文档数。"""
    try:
        client = _get_chroma_client(persist_dir)
        coll = _get_or_create_collection(client, namespace)
        return coll.count()
    except Exception:
        return 0


# ── 混合搜索（RRF 融合） ──

def hybrid_search(
    persist_dir: Path,
    namespace: str,
    query: str,
    *,
    fts_results: list[dict[str, Any]] | None = None,
    limit: int = 10,
    vector_weight: float = 0.6,
    keyword_weight: float = 0.4,
) -> list[dict[str, Any]]:
    """向量 + 关键词 RRF (Reciprocal Rank Fusion) 混合排序。

    参数:
        fts_results: FTS/关键词搜索结果列表（key → score 映射）
        limit: 返回数量
        vector_weight / keyword_weight: 融合权重（默认向量 60%，关键词 40%）
    """
    # 向量检索
    vec_results = vector_search(persist_dir, namespace, query, limit=max(limit * 2, 20))

    # RRF 融合
    scores: dict[str, dict[str, Any]] = {}
    k = 60  # RRF 常数

    for rank, item in enumerate(vec_results):
        kid = item["key"]
        if kid not in scores:
            scores[kid] = dict(item)
            scores[kid]["_rrf"] = 0.0
        scores[kid]["_rrf"] += vector_weight * (1.0 / (k + rank + 1))
        scores[kid].setdefault("score", 0.0)

    if fts_results:
        for rank, item in enumerate(fts_results):
            kid = item.get("key", "")
            if not kid:
                continue
            if kid not in scores:
                scores[kid] = dict(item)
                scores[kid]["_rrf"] = 0.0
            scores[kid]["_rrf"] += keyword_weight * (1.0 / (k + rank + 1))
            # 保留关键词分数
            if "score" not in scores[kid] or scores[kid]["score"] == 0:
                scores[kid]["score"] = item.get("score", 0)

    # 按 RRF 分数排序
    ranked = sorted(scores.values(), key=lambda x: x.get("_rrf", 0), reverse=True)
    for item in ranked:
        item["source"] = "hybrid"
        item.pop("_rrf", None)

    return ranked[:limit]


def is_vector_available() -> bool:
    """检查 ChromaDB 是否可用。"""
    try:
        import chromadb  # noqa: F401
        return True
    except ImportError:
        return False
