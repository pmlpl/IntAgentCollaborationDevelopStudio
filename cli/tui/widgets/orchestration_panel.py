# cli/tui/widgets/orchestration_panel.py — 编排进度条文本
from __future__ import annotations

from core.dispatch.orchestration_progress import OrchestrationProgress


def _step_line(step) -> str:
    if step.done:
        mark = "[green]✓[/]"
    elif step.active:
        mark = "[yellow]▶[/]"
    else:
        mark = "[dim]○[/]"
    label = step.label
    if step.active:
        label = f"[bold]{label}[/]"
    line = f"  {mark} {label}"
    detail = getattr(step, "detail", "") or ""
    if detail and (step.active or step.done):
        line += f" [dim]({detail})[/]"
    return line


def render_orchestration_panel(progress: OrchestrationProgress) -> str:
    """渲染编排进度面板（含文本进度条）。"""
    filled = max(0, min(20, progress.percent // 5))
    bar = "[cyan]" + "█" * filled + "[/][dim]" + "░" * (20 - filled) + "[/]"
    lines = [
        "[bold magenta]▸ 任务编排进度[/]",
        "",
        f"任务: {progress.description[:60]}",
        f"id: {progress.task_id}",
        "",
        f"{bar} {progress.percent:3d}%",
        f"[italic]{progress.message}[/]",
        "",
        "[bold]步骤[/]",
    ]
    lines.extend(_step_line(s) for s in progress.steps)
    if progress.done:
        lines.extend(["", "[green]编排已完成[/]"])
    elif progress.failed:
        lines.extend(["", "[red]编排失败，请查看主管终端输出[/]"])
    return "\n".join(lines)
