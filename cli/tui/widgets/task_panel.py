# cli/tui/widgets/task_panel.py — 任务与进度面板文本
from __future__ import annotations

from typing import Any

from core.runtime.state import AgentRuntimeState


def _bar(progress: int) -> str:
    filled = max(0, min(10, progress // 10))
    return "█" * filled + "░" * (10 - filled)


def render_task_panel(
    tasks: list[dict[str, Any]],
    positions: list[dict[str, Any]],
    states: dict[str, AgentRuntimeState],
    *,
    highlight_task_id: str | None = None,
) -> str:
    lines = ["[bold cyan]任务与进度[/]", ""]
    if not tasks:
        lines.append("[dim]暂无任务。按 N 下达新任务。[/]")
    for t in tasks:
        if t.get("parent_id"):
            continue
        desc = t.get("description", "")[:50]
        tid = t.get("id")
        if highlight_task_id and tid == highlight_task_id:
            lines.append(f"▸ [bold reverse]{desc}[/]")
        else:
            lines.append(f"▸ {desc}")
        lines.append(f"  状态: [yellow]{t.get('status')}[/]  id={tid}")
        lines.append("")
    if highlight_task_id:
        subs = [t for t in tasks if t.get("parent_id") == highlight_task_id]
        if subs:
            lines.append("[bold]子任务[/]")
            for st in subs:
                assignee = st.get("assignee", "?")
                lines.append(
                    f"  · [{st.get('status')}] {assignee}: "
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
