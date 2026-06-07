# core/org/org_chart.py — CLI 用组织树渲染
from __future__ import annotations

from typing import Any

from core.org.tree_ops import OrgTree


def render_tree(positions: list[dict[str, Any]]) -> str:
    """将 positions 渲染为 ASCII 树形结构。"""
    tree = OrgTree(positions)
    by_parent: dict[str | None, list[dict]] = {}
    for pos in positions:
        parent = pos.get("parent")
        by_parent.setdefault(parent, []).append(pos)

    lines: list[str] = []

    def walk(parent_id: str | None, prefix: str = "") -> None:
        children = by_parent.get(parent_id, [])
        for i, child in enumerate(children):
            is_last = i == len(children) - 1
            connector = "└── " if is_last else "├── "
            title = child.get("title", child.get("id", ""))
            name = child.get("name", "")
            lines.append(f"{prefix}{connector}{name} ({title})")
            extension = "    " if is_last else "│   "
            walk(child["id"], prefix + extension)

    walk(None)
    return "\n".join(lines) if lines else "(empty org)"
