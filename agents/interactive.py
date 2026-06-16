# agents/interactive.py — 各 Agent CLI 交互式 TUI 启动命令构建
from __future__ import annotations

from pathlib import Path
from typing import Any

from agents.execute import prepare_subprocess_argv
from agents.goose_env import goose_provider_configured
from core.dispatch.delivery import DELIVER_REL

# 任务上下文写入 worktree/.studio/STUDIO_TASK.md（相对 cwd）
STUDIO_TASK_REL = ".studio/STUDIO_TASK.md"
# Hermes 启动时自动注入项目根目录的上下文文件（见 hermes_cli tips）
HERMES_CONTEXT_REL = ".hermes.md"


def _deliver_json_template(task_id: str = "", role: str = "") -> str:
    """Generate the DELIVER.json JSON template string."""
    return (
        f"{{\n"
        f'  "task_id": "{task_id or "TASK_ID"}",\n'
        f'  "assignee": "{role or "YOUR_ROLE_ID"}",\n'
        f'  "status": "completed",\n'
        f'  "summary": "What you built and how it works (English, 2-5 sentences)",\n'
        f'  "files": ["path/to/main.py", "path/to/other.js"],\n'
        f'  "run_command": "python main.py",\n'
        f'  "run_ok": true\n'
        f"}}"
    )


def format_task_prompt(description: str, *, task_id: str = "", role: str = "", assignee_id: str = "") -> str:
    """Generate STUDIO_TASK.md prompt with DELIVER.json as the central requirement.

    The prompt is structured so the agent CANNOT miss the delivery requirement:
    - CRITICAL banner at the top (first thing the agent sees)
    - Task description in the middle
    - Step-by-step delivery checklist at the bottom (last thing before the agent acts)
    """
    header_parts = []
    if role:
        header_parts.append(f"Studio · {role}")
    if task_id:
        header_parts.append(f"Task {task_id}")
    header = " | ".join(header_parts) if header_parts else "Studio Task"
    deliver_path = DELIVER_REL.as_posix()
    # Use assignee_id (position ID like "xiaohong") if provided, otherwise fall back to role
    deliver_assignee = assignee_id or role or "YOUR_ROLE_ID"
    deliver_json = _deliver_json_template(task_id, deliver_assignee)

    return (
        f"# {header}\n\n"
        # ── CRITICAL: first thing the agent reads ──
        f"## !! CRITICAL — READ THIS FIRST !!\n"
        f"Your work is NOT complete until you write the delivery file.\n"
        f"The system CANNOT detect that you finished unless you create `{deliver_path}`.\n"
        f"If you skip this step, your work will be LOST — the pipeline will stall forever.\n\n"
        # ── Task description ──
        f"## Your Task\n"
        f"{description.strip()}\n\n"
        # ── Language policy ──
        f"## Language Policy\n"
        f"- Communicate in English with your tech lead and teammates\n"
        f"- The tech lead summarizes final results to CEO in Chinese (中文)\n"
        f"- Write all code comments, commit messages, and documentation in English\n\n"
        # ── How to work ──
        f"## How to Work\n"
        f"- You are in an isolated git worktree. Read/write files and run commands directly.\n"
        f"- Verify your work: run tests, start the app, check for errors.\n\n"
        # ── DELIVER.json specification ──
        f"## Delivery Protocol — YOUR FINAL STEP\n"
        f"After you have implemented AND verified your work, create `{deliver_path}`:\n\n"
        f"```json\n{deliver_json}\n```\n\n"
        f"**Field descriptions:**\n"
        f"- `task_id`: your assigned task ID (shown above)\n"
        f"- `assignee`: your position/role ID\n"
        f"- `status`: \"completed\" if successful, \"failed\" if blocked\n"
        f"- `summary`: what you implemented (English, 2-5 sentences)\n"
        f"- `files`: ALL files you created or modified (relative paths from worktree root)\n"
        f"- `run_command`: the exact shell command to run/verify your work\n"
        f"- `run_ok`: true if your `run_command` exited with code 0\n\n"
        f"Once you write this file, the system auto-detects it, runs verification,\n"
        f"and notifies your tech lead for review. Nothing else is needed.\n\n"
        # ── FINAL CHECKLIST reminder at the very bottom ──
        f"## Before You Consider Yourself Done\n"
        f"- [ ] Did I implement the task described above?\n"
        f"- [ ] Did I verify my work (run it, test it, check for errors)?\n"
        f"- [ ] Did I write `{deliver_path}` with all required fields?\n\n"
        f"If you checked all three boxes, you are done. If `{deliver_path}` is\n"
        f"missing, YOU ARE NOT DONE. Write it now."
    )


def write_hermes_context_file(worktree: Path, prompt: str) -> Path:
    """写入 .hermes.md，Hermes TUI 启动时会自动加载为项目上下文。"""
    path = worktree / HERMES_CONTEXT_REL
    path.write_text(prompt, encoding="utf-8")
    return path


def write_agents_context_file(worktree: Path, prompt: str) -> Path:
    """写入 AGENTS.md（Hermes 在 .hermes.md 缺失时的备选项目上下文）。"""
    path = worktree / "AGENTS.md"
    path.write_text(prompt, encoding="utf-8")
    return path


def build_hermes_tui_query(task_id: str = "", task_file_rel: Path | None = None) -> str:
    """Hermes TUI 首条自动提交消息（短句，避免 Windows 命令行拆参）。"""
    rel = str(task_file_rel or STUDIO_TASK_REL)
    tid = f"任务 {task_id}：" if task_id else ""
    return (
        f"【Studio 已派任务】{tid}请先阅读 {rel} 与 .hermes.md，"
        f"按其中的 CEO 总目标与子任务说明立即开始实现。"
    )


def prepare_hermes_worker_context(
    worktree: Path,
    task_body: str,
    *,
    task_id: str = "",
    task_file_rel: Path | None = None,
) -> dict[str, str]:
    """写入 Hermes 项目上下文文件，并生成 TUI 首条 query 环境变量。"""
    write_hermes_context_file(worktree, task_body)
    write_agents_context_file(worktree, task_body)
    return {
        "HERMES_TUI_QUERY": build_hermes_tui_query(task_id, task_file_rel=task_file_rel),
    }


def write_task_context_file(worktree: Path, prompt: str) -> Path:
    """写入 .studio/STUDIO_TASK.md，返回相对路径。"""
    studio_dir = worktree / ".studio"
    studio_dir.mkdir(parents=True, exist_ok=True)
    (studio_dir / "STUDIO_TASK.md").write_text(prompt, encoding="utf-8")
    return Path(STUDIO_TASK_REL)


def build_interactive_argv(
    cfg: dict[str, Any],
    *,
    task_file_rel: Path | None = None,
    worktree: Path | None = None,
) -> list[str]:
    """根据 agents.yaml 构建交互式 TUI 命令（尽量自动把任务注入 Agent 会话）。"""
    command = str(cfg.get("command") or "")
    if not command:
        raise ValueError("agent config missing command")

    if command == "goose" and not goose_provider_configured():
        # 未 configure 时 session 会秒退；改为打开配置向导
        argv = [command, "configure"]
        return prepare_subprocess_argv(argv, interactive=True)

    argv: list[str] = [command]
    flags_i = cfg.get("flags_interactive")
    flags_parts: list[str] = (
        str(flags_i).split() if flags_i is not None and str(flags_i).strip() else []
    )

    interactive = cfg.get("interactive") if isinstance(cfg.get("interactive"), dict) else {}
    mode = str(interactive.get("mode") or "task_file_context")
    rel = task_file_rel or Path(STUDIO_TASK_REL)
    rel_str = str(rel)

    if mode == "append_system_prompt_file":
        argv.extend(flags_parts)
        if not task_file_rel:
            raise ValueError("append_system_prompt_file requires task_file_rel")
        argv.extend(["--append-system-prompt-file", rel_str])
    elif mode == "prompt_flag":
        # Hermes 等：-z 为全局参数，必须在 chat 等子命令之前
        flag = str(interactive.get("flag") or "-z")
        prompt_text = str(interactive.get("prompt_text") or "file").strip().lower()
        if prompt_text == "starter":
            text = starter_fallback(interactive, rel_str)
        else:
            text = _read_task_file_excerpt(worktree, rel, max_chars=8000)
            if not text.strip():
                text = starter_fallback(interactive, rel_str)
        text += _deliver_reminder()
        argv.extend([flag, text])
        argv.extend(flags_parts)
    elif mode == "run_interactive":
        # OpenCode: "run <message>" — positional message, no -i flag
        argv.extend(flags_parts)
        text = _read_task_file_excerpt(worktree, rel, max_chars=8000)
        if not text.strip():
            text = starter_fallback(interactive, rel_str)
        text += _deliver_reminder()
        argv.extend(["run", text])
    elif mode == "initial_prompt":
        argv.extend(flags_parts)
        flag = str(interactive.get("flag") or "--prompt")
        text = _read_task_file_excerpt(worktree, rel, max_chars=6000)
        if not text.strip():
            text = starter_fallback(interactive, rel_str)
        text += _deliver_reminder()
        argv.extend([flag, text])
    else:
        # task_file_context：仅写 STUDIO_TASK.md，不自动发消息（旧行为）
        argv.extend(flags_parts)

    extra = interactive.get("append_args") or []
    if isinstance(extra, list):
        for item in extra:
            part = str(item).replace("{task_file}", rel_str)
            argv.append(part)

    return prepare_subprocess_argv(argv, interactive=True)


def _deliver_reminder() -> str:
    """Short reminder appended to CLI-passed task text so the agent doesn't forget."""
    deliver_path = DELIVER_REL.as_posix()
    return (
        f"\n\n---\n"
        f"!! WHEN DONE: write {deliver_path} with task_id, assignee, status, "
        f"summary, files, run_command, run_ok. "
        f"Your work is invisible to the system until you do this. !!"
    )


def starter_fallback(interactive: dict[str, Any], rel_str: str) -> str:
    """无任务文件时的占位首条消息。"""
    tpl = str(
        interactive.get("starter_message")
        or "请阅读 {task_file} 并按说明执行。"
    )
    return tpl.replace("{task_file}", rel_str)


def _read_task_file_excerpt(worktree: Path | None, rel: Path, *, max_chars: int = 6000) -> str:
    """读取 worktree 内任务文件摘要，供 --prompt 等使用。"""
    if worktree is None:
        return ""
    path = worktree / rel
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 20] + "\n…（详见 STUDIO_TASK.md）"


def format_worker_task_prompt(
    project_dir: Path | None,
    subtask_description: str,
    *,
    task_id: str = "",
    role: str = "",
    assignee_id: str = "",
) -> str:
    """Merge CEO brief + sub-task description for STUDIO_TASK.md.

    Includes completed sibling task summaries (project memory) so new workers
    understand the context before starting.
    """
    sections: list[str] = []
    if project_dir is not None:
        from core.dispatch.briefing import ceo_context_for_workers

        ceo_ctx = ceo_context_for_workers(project_dir)
        if ceo_ctx:
            sections.append(f"## CEO Confirmed Goal\n{ceo_ctx}")

        # Accumulate completed task summaries (project memory)
        completed = _load_completed_sibling_summaries(project_dir, task_id)
        if completed:
            sections.append(f"## Completed Work by Teammates\n{completed}")

    sections.append(f"## Your Sub-task\n{subtask_description.strip()}")
    body = "\n\n".join(sections)
    return format_task_prompt(body, task_id=task_id, role=role, assignee_id=assignee_id)


def _load_completed_sibling_summaries(project_dir: Path, current_task_id: str) -> str:
    """读取当前编排中已完成子任务的交付摘要，累积为项目记忆。

    最多返回 1500 字符，避免撑爆 Agent 上下文窗口。
    """
    import json as _json

    lines: list[str] = []
    active_dir = project_dir / "tasks" / "active"
    if not active_dir.is_dir():
        return ""

    # 收集已归档/已审批的任务
    archive_dir = project_dir / "tasks" / "archive"
    archived_summaries: list[tuple[str, str]] = []
    if archive_dir.is_dir():
        for path in sorted(archive_dir.glob("*.yaml")):
            try:
                import yaml as _yaml
                t = _yaml.safe_load(path.read_text(encoding="utf-8"))
                tid = str(t.get("id") or "")
                summary = str(t.get("review_comment") or t.get("description") or "")
                if tid and summary:
                    archived_summaries.append((tid, summary[:200]))
            except Exception:
                pass

    # 收集进行中但已有交付记录的任务
    delivery_summaries: list[tuple[str, str]] = []
    for path in sorted(active_dir.glob(".delivery-*.json")):
        try:
            rec = _json.loads(path.read_text(encoding="utf-8"))
            tid = str(rec.get("task_id") or "")
            summary = str(rec.get("summary") or "")
            if tid and summary and tid != current_task_id:
                exit_code = rec.get("exit_code", -1)
                status_icon = "✓" if exit_code == 0 else "✗"
                delivery_summaries.append((tid, f"[{status_icon}] {summary[:200]}"))
        except Exception:
            pass

    if archived_summaries:
        lines.append("Approved & merged:")
        for tid, summary in archived_summaries[:5]:
            lines.append(f"  - {summary}")
    if delivery_summaries:
        lines.append("Delivered (pending review):")
        for tid, summary in delivery_summaries[:5]:
            lines.append(f"  - {summary}")

    result = "\n".join(lines)
    return result[:1500]
