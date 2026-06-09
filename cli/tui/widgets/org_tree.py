# cli/tui/widgets/org_tree.py — 组织树 Rich 文本渲染
from __future__ import annotations

from typing import Any

from rich.tree import Tree


def render_org_tree(positions: list[dict[str, Any]]) -> str:
    """将 positions 转为 Rich 树文本（供 Static 显示）。"""
    by_parent: dict[str | None, list[dict]] = {}
    for pos in positions:
        by_parent.setdefault(pos.get("parent"), []).append(pos)

    root = Tree("[bold cyan]组织架构[/]")
    id_to_branch: dict[str, Tree] = {}

    def attach(parent_key: str | None, branch: Tree) -> None:
        for child in by_parent.get(parent_key, []):
            agent = child.get("agent", "?")
            label = f"[green]{child.get('name', child['id'])}[/] ({child.get('title', '')}) · {agent}"
            sub = branch.add(label)
            id_to_branch[child["id"]] = sub
            attach(child["id"], sub)

    attach(None, root)

    from io import StringIO

    from rich.console import Console

    buf = StringIO()
    Console(file=buf, width=40, legacy_windows=False).print(root)
    return buf.getvalue()
