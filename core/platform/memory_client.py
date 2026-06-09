# core/platform/memory_client.py — 记忆中台（文件后端，可扩展 ChromaDB）
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from core.org.tree_ops import OrgTree
from core.rbac.permission import memory_access


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
    """写入或更新一条记忆。"""
    tree = _load_tree(project_dir)
    _check_access(tree, position, namespace, write=True, project_id=project_id)
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
    """删除一条记忆。"""
    tree = _load_tree(project_dir)
    _check_access(tree, position, namespace, write=True, project_id=project_id)
    path = _entry_path(root, namespace, key)
    if path.exists():
        path.unlink()
        return True
    return False


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
    """简单关键词搜索（文件后端；后续可换 ChromaDB）。"""
    tree = _load_tree(project_dir)
    _check_access(tree, position, namespace, write=False, project_id=project_id)
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
    """列出已有记忆的命名空间。"""
    base = store_root(root)
    if not base.exists():
        return []
    result: list[str] = []
    for child in base.iterdir():
        if child.is_dir():
            result.append(child.name.replace("__", "/"))
    return sorted(result)
