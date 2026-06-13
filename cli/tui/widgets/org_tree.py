# cli/tui/widgets/org_tree.py — 组织树 Rich 文本渲染
from __future__ import annotations

from typing import Any

from rich.tree import Tree


def render_org_tree(positions: list[dict[str, Any]]) -> str:
    """将 positions 转为 Rich 树文本（供 Static 显示）。

    带 Agent 启用/禁用颜色标注。
    """
    from core.config.agent_policy import agent_enabled
    from core.project import get_studio_root

    root_path = get_studio_root()

    by_parent: dict[str | None, list[dict]] = {}
    for pos in positions:
        by_parent.setdefault(pos.get("parent"), []).append(pos)

    tree = Tree("[bold cyan]组织架构[/]")

    def _agent_label(pos: dict) -> str:
        agent_id = pos.get("agent", "")
        if not agent_id:
            return ""
        try:
            if agent_enabled(root_path, agent_id):
                return f"[dim green]◉[/] {agent_id}"
            else:
                return f"[dim red]◉[/] {agent_id}"
        except Exception:
            return f"{agent_id}"

    def attach(parent_key: str | None, branch: Tree) -> None:
        for child in by_parent.get(parent_key, []):
            name = child.get("name", child["id"])
            title = child.get("title", "")
            agent = _agent_label(child)

            is_mgr = child.get("is_manager")
            if is_mgr:
                label = f"[bold white]{name}[/] [dim]({title})[/]"
            else:
                label = f"[white]{name}[/] [dim]({title})[/]"

            if agent:
                label += f" · {agent}"

            sub = branch.add(label)
            attach(child["id"], sub)

    attach(None, tree)

    from io import StringIO
    from rich.console import Console

    buf = StringIO()
    Console(file=buf, width=40, legacy_windows=False).print(tree)
    return buf.getvalue()
