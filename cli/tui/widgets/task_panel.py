# cli/tui/widgets/task_panel.py — 任务与进度面板文本
from __future__ import annotations

from typing import Any

from core.runtime.state import AgentRuntimeState

_STATUS_ICONS = {
    "pending": "[dim]○[/]",
    "assigned": "[dim]○[/]",
    "in_progress": "[bold yellow]▶[/]",
    "blocked": "[bold red]⊗[/]",
    "submitted": "[cyan]◆[/]",
    "in_review": "[bold cyan]◆[/]",
    "approved": "[bold green]✓[/]",
    "rejected": "[bold red]✗[/]",
    "escalated": "[bold magenta]↑[/]",
    "archived": "[dim]📦[/]",
}


def _status_icon(status: str) -> str:
    return _STATUS_ICONS.get(status, "[dim]?[/]")


def _bar(progress: int) -> str:
    filled = max(0, min(10, progress // 10))
    if filled == 0:
        return "[dim]" + "░" * 10 + "[/]"
    if filled == 10:
        return "[bold green]" + "█" * 10 + "[/]"
    return "[bold green]" + "█" * filled + "[/][dim]" + "░" * (10 - filled) + "[/]"


def render_task_panel(
    tasks: list[dict[str, Any]],
    positions: list[dict[str, Any]],
    states: dict[str, AgentRuntimeState],
    *,
    highlight_task_id: str | None = None,
) -> str:
    lines = ["[bold cyan]任务与进度[/]", ""]
    if not tasks:
        lines.append("[dim]暂无任务。[/]")
        lines.append("[dim]按 N 下达新任务。[/]")
    for t in tasks:
        if t.get("parent_id"):
            continue
        desc = t.get("description", "")[:48]
        tid = t.get("id")
        status = str(t.get("status", ""))
        icon = _status_icon(status)
        if highlight_task_id and tid == highlight_task_id:
            lines.append(f"{icon} [bold reverse]{desc}[/]")
        else:
            lines.append(f"{icon} {desc}")
        lines.append(f"   [dim]{status}[/]  [dim]id={tid}[/]")
        lines.append("")
    if highlight_task_id:
        subs = [t for t in tasks if t.get("parent_id") == highlight_task_id]
        if subs:
            lines.append("[bold]子任务[/]")
            for st in subs:
                assignee = st.get("assignee", "?")
                icon = _status_icon(str(st.get("status", "")))
                lines.append(
                    f"  {icon} [dim]{assignee}:[/] "
                    f"{st.get('description', '')[:36]}"
                )
            lines.append("")
    lines.append("[bold]岗位进度[/]")
    id_to_name = {p["id"]: p.get("name", p["id"]) for p in positions}
    for pid, state in states.items():
        if pid.startswith("__"):
            continue
        name = id_to_name.get(pid, pid)
        bar = _bar(state.progress)
        lines.append(
            f"  {name:6} {bar} {state.progress:3d}%  [{state.status}] {state.message}"
        )
    return "\n".join(lines)
