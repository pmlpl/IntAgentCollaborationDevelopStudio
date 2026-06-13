# core/platform/memory_client.py — 记忆中台（文件后端，SQLite FTS5 后端）
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from core.logging import get_logger
from core.org.tree_ops import OrgTree
from core.rbac.permission import memory_access

logger = get_logger(__name__)


class MemoryError(Exception):
    """记忆中台异常。"""


def _platform_config(root: Path) -> dict[str, Any]:
    path = root / "config" / "platform.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def store_root(root: Path) -> Path:
    cfg = _platform_config(root).get("memory") or {}
    rel = cfg.get("store_dir", "platform/memory/store")
    return (root / rel).resolve()


def _entry_path(root: Path, namespace: str, key: str) -> Path:
    safe_key = re.sub(r"[^\w\-.]", "_", key)
    return store_root(root) / namespace.replace("/", "__") / f"{safe_key}.json"


def resolve_memory_namespace(namespace: str, project_id: str) -> str:
    """将 CLI 输入解析为 canonical 命名空间；project  shorthand 绑定当前项目 id。"""
    ns = namespace.strip()
    if ns in ("project", "project/"):
        return f"project/{project_id}"
    if ns.startswith("project/"):
        suffix = ns.split("/", 1)[1]
        if suffix != project_id:
            raise MemoryError(
                f"命名空间 {ns!r} 与当前项目 {project_id!r} 不一致。"
                f"请改用: project/{project_id}  或简写: project"
            )
    return ns


def _load_tree(project_dir: Path) -> OrgTree:
    data = yaml.safe_load((project_dir / "positions.yaml").read_text(encoding="utf-8"))
    return OrgTree.from_yaml_data(data)


def _check_access(
    tree: OrgTree,
    position: dict[str, Any],
    namespace: str,
    *,
    write: bool,
    project_id: str | None,
) -> None:
    level = memory_access(tree, position, namespace, project_id=project_id)
    if level == "none":
        raise MemoryError(f"无权访问命名空间: {namespace}")
    if write and level != "read_write":
        raise MemoryError(f"无权写入命名空间: {namespace}")


def upsert(
    root: Path,
    project_dir: Path,
    position: dict[str, Any],
    namespace: str,
    key: str,
    text: str,
    *,
    project_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Path:
    """写入或更新一条记忆（文件 + SQLite FTS + 可选 ChromaDB 向量）。"""
    tree = _load_tree(project_dir)
    _check_access(tree, position, namespace, write=True, project_id=project_id)

    backend = _resolve_backend(root)

    # 文件写入（始终执行，作为主存储）
    file_path = _file_upsert(root, namespace, key, text, position, metadata)

    # SQLite FTS 写入
    if backend in ("sqlite", "chromadb"):
        _fts_upsert(root, namespace, key, text, position.get("id", "unknown"))

    # ChromaDB 向量写入
    if backend == "chromadb":
        try:
            from core.platform.vector_memory import vector_upsert
            persist_dir = store_root(root) / "chromadb"
            update_by = position.get("id", "unknown")
            vector_upsert(
                persist_dir, namespace, key, text,
                metadata={"updated_by": update_by, **(metadata or {})},
            )
        except Exception as exc:
            logger.warning("ChromaDB vector_upsert failed for %s/%s: %s", namespace, key, exc)
            # 向量写入失败不阻止整体写入（降级而非中断）

    return file_path


def _file_upsert(
    root: Path,
    namespace: str,
    key: str,
    text: str,
    position: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> Path:
    path = _entry_path(root, namespace, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "namespace": namespace,
        "key": key,
        "text": text,
        "metadata": metadata or {},
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "updated_by": position.get("id"),
    }
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def delete(
    root: Path,
    project_dir: Path,
    position: dict[str, Any],
    namespace: str,
    key: str,
    *,
    project_id: str | None = None,
) -> bool:
    """删除一条记忆（文件 + SQLite FTS + 可选 ChromaDB）。"""
    tree = _load_tree(project_dir)
    _check_access(tree, position, namespace, write=True, project_id=project_id)

    backend = _resolve_backend(root)
    deleted = False

    # FTS 删除
    if backend in ("sqlite", "chromadb"):
        try:
            deleted = _fts_delete(root, namespace, key)
        except Exception:
            pass

    # ChromaDB 删除
    if backend == "chromadb":
        try:
            from core.platform.vector_memory import vector_delete
            vector_delete(store_root(root) / "chromadb", namespace, key)
        except Exception as exc:
            logger.warning("ChromaDB vector_delete failed: %s", exc)

    # 文件删除
    path = _entry_path(root, namespace, key)
    if path.exists():
        path.unlink()
        return True
    return deleted


def search(
    root: Path,
    project_dir: Path,
    position: dict[str, Any],
    namespace: str,
    query: str,
    *,
    project_id: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """记忆搜索：ChromaDB 向量 > SQLite FTS5 > 文件回退。

    后端为 chromadb 时：向量检索 + FTS RRF 混合排序（语义 + 关键词双通路）。
    """
    tree = _load_tree(project_dir)
    _check_access(tree, position, namespace, write=False, project_id=project_id)

    backend = _resolve_backend(root)

    if backend == "chromadb":
        try:
            persist_dir = store_root(root) / "chromadb"
            fts_results = None
            try:
                fts_results = _fts_search(root, namespace, query, limit)
            except Exception:
                pass
            from core.platform.vector_memory import hybrid_search
            return hybrid_search(
                persist_dir, namespace, query,
                fts_results=fts_results,
                limit=limit,
            )
        except Exception as exc:
            logger.warning("ChromaDB hybrid search failed, falling back to FTS: %s", exc)

    if backend == "sqlite":
        try:
            return _fts_search(root, namespace, query, limit)
        except Exception as exc:
            logger.warning("FTS search failed, falling back to file: %s", exc)

    return _file_search(root, namespace, query, limit)


def _file_search(
    root: Path, namespace: str, query: str, limit: int = 10,
) -> list[dict[str, Any]]:
    """简单关键词搜索（文件后端）。"""
    ns_dir = store_root(root) / namespace.replace("/", "__")
    if not ns_dir.exists():
        return []
    tokens = [t.lower() for t in re.split(r"\s+", query.strip()) if t]
    hits: list[tuple[int, dict[str, Any]]] = []
    for path in ns_dir.glob("*.json"):
        record = json.loads(path.read_text(encoding="utf-8"))
        text = (record.get("text") or "").lower()
        score = sum(1 for tok in tokens if tok in text) if tokens else 1
        if score > 0:
            hits.append((score, record))
    hits.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in hits[:limit]]


def list_namespaces(root: Path) -> list[str]:
    """列出已有记忆的命名空间（合并文件 + SQLite FTS + ChromaDB）。"""
    backend = _resolve_backend(root)
    namespaces: set[str] = set()

    # ChromaDB
    if backend == "chromadb":
        try:
            from core.platform.vector_memory import vector_list_namespaces
            namespaces.update(vector_list_namespaces(store_root(root) / "chromadb"))
        except Exception:
            pass

    # SQLite FTS
    if backend in ("sqlite", "chromadb"):
        try:
            db = _get_fts_db(root)
            rows = db.execute("SELECT DISTINCT namespace FROM memory_index").fetchall()
            namespaces.update(r[0] for r in rows if r[0])
        except Exception:
            pass

    # 文件
    base = store_root(root)
    if base.exists():
        for child in base.iterdir():
            if child.is_dir() and not child.name.startswith("chromadb"):
                namespaces.add(child.name.replace("__", "/"))

    return sorted(namespaces)


# ── SQLite FTS5 后端 ──

def _resolve_backend(root: Path) -> str:
    cfg = _platform_config(root).get("memory") or {}
    backend = str(cfg.get("backend", "file")).strip().lower()
    if backend == "chromadb":
        from core.platform.vector_memory import is_vector_available
        if not is_vector_available():
            logger.warning("chromadb not installed, falling back to sqlite")
            return "sqlite"
    return backend


def _fts_db_path(root: Path) -> Path:
    return store_root(root) / "memory_fts.db"


def _get_fts_db(root: Path) -> sqlite3.Connection:
    """获取或创建 SQLite FTS5 数据库连接。"""
    db_path = _fts_db_path(root)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS memory_index USING fts5("
        "namespace, key, text, updated_at, updated_by, "
        "tokenize='unicode61 remove_diacritics 1'"
        ")"
    )
    return conn


def _fts_upsert(root: Path, namespace: str, key: str, text: str, updated_by: str) -> None:
    db = _get_fts_db(root)
    # 删除旧记录
    db.execute(
        "DELETE FROM memory_index WHERE namespace=? AND key=?",
        (namespace, key),
    )
    db.execute(
        "INSERT INTO memory_index (namespace, key, text, updated_at, updated_by) "
        "VALUES (?, ?, ?, ?, ?)",
        (namespace, key, text, datetime.now(timezone.utc).isoformat(), updated_by),
    )
    db.commit()


def _fts_search(
    root: Path, namespace: str, query: str, limit: int = 10,
) -> list[dict[str, Any]]:
    db = _get_fts_db(root)
    # FTS5 语法：简单关键词用 MATCH，多个词用 AND
    terms = re.split(r"\s+", query.strip())
    if not terms:
        return []
    fts_query = " AND ".join(f'"{t}"' for t in terms if t)
    try:
        rows = db.execute(
            "SELECT namespace, key, text, updated_at, updated_by, "
            "rank FROM memory_index "
            "WHERE memory_index MATCH ? AND namespace=? "
            "ORDER BY rank LIMIT ?",
            (fts_query, namespace, limit),
        ).fetchall()
    except sqlite3.OperationalError:
        # FTS 查询语法错误时回退到 LIKE
        like = f"%{query}%"
        rows = db.execute(
            "SELECT namespace, key, text, updated_at, updated_by, "
            "1 FROM memory_index "
            "WHERE namespace=? AND text LIKE ? "
            "LIMIT ?",
            (namespace, like, limit),
        ).fetchall()
    return [
        {
            "namespace": r[0],
            "key": r[1],
            "text": r[2],
            "updated_at": r[3],
            "updated_by": r[4],
        }
        for r in rows
    ]


def _fts_delete(root: Path, namespace: str, key: str) -> bool:
    db = _get_fts_db(root)
    cur = db.execute(
        "DELETE FROM memory_index WHERE namespace=? AND key=?", (namespace, key)
    )
    db.commit()
    return cur.rowcount > 0


def _fts_list_namespaces(root: Path) -> list[str]:
    db = _get_fts_db(root)
    rows = db.execute("SELECT DISTINCT namespace FROM memory_index").fetchall()
    return sorted(set(r[0] for r in rows if r[0]))
