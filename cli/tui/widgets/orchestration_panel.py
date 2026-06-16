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
    """Render orchestration progress panel with dynamic counts.

    Shows a unicode progress bar, step-by-step status, and live worker/delivery/review counts.
    """
    filled = max(0, min(20, progress.percent // 5))
    if progress.failed:
        bar = "[red]" + "█" * filled + "[/][dim]" + "░" * (20 - filled) + "[/]"
    elif filled == 0:
        bar = "[dim]" + "░" * 20 + "[/]"
    elif filled == 20:
        bar = "[bold green]" + "█" * 20 + "[/]"
    else:
        bar = "[bold cyan]" + "█" * filled + "[/][dim]" + "░" * (20 - filled) + "[/]"

    lines = [
        "[bold]▸ 任务编排进度[/]",
        "",
        f"任务: {progress.description[:60]}",
        f"id: [dim]{progress.task_id}[/]",
        "",
        f"{bar} [bold]{progress.percent:3d}%[/]",
        f"[italic]{progress.message}[/]",
    ]

    # Live counters when there are subtasks
    if progress.total_children > 0:
        counter_parts = [f"子任务: {progress.total_children}"]
        if progress.delivered_count > 0:
            counter_parts.append(f"已交付: [cyan]{progress.delivered_count}[/]")
        if progress.reviewed_count > 0:
            counter_parts.append(f"已审查: [yellow]{progress.reviewed_count}[/]")
        if progress.archived_count > 0:
            counter_parts.append(f"已归档: [green]{progress.archived_count}[/]")
        lines.append(" · ".join(counter_parts))

    lines.extend(["", "[bold]步骤[/]"])
    lines.extend(_step_line(s) for s in progress.steps)

    if progress.done:
        lines.extend(["", f"[bold green]✓ 全部完成 — {progress.archived_count}/{progress.total_children} 已归档[/]"])
    elif progress.failed:
        lines.extend(["", "[bold red]✗ 编排失败，请查看主管终端输出[/]"])
    return "\n".join(lines)
