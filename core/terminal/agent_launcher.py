# core/terminal/agent_launcher.py — 在终端中直接启动各 Agent 交互式 TUI
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agents.execute import (
    agent_launch_check_error,
    agent_subprocess_env,
    prepare_subprocess_argv,
)
from agents.interactive import (
    STUDIO_TASK_REL,
    build_interactive_argv,
    format_task_prompt,
    format_worker_task_prompt,
    prepare_hermes_worker_context,
    write_task_context_file,
)
from cli.relay_agent import wrap_argv_for_windows_terminal
from agents.registry import load_agent_config, load_agents_config
from agents.runner import agent_available, load_position
from core.config.agent_policy import agent_allowed, agent_is_byok, agent_policy, pick_spawn_agent_id
from core.platform.skills_client import prepare_worker_runtime
from core.runtime.state import AgentRuntimeState, write_state
from core.terminal.spawner import spawn_agent_terminal


def _orchestration_settings(root: Path) -> dict[str, Any]:
    """读取 platform.yaml orchestration 段。"""
    path = root / "config" / "platform.yaml"
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    orch = data.get("orchestration")
    return orch if isinstance(orch, dict) else {}


def resolve_spawn_agent_id(root: Path, position_agent_id: str) -> str:
    """Worker 编排时选用哪个 Agent：跟岗位或 platform 覆盖，并受 BYOK 策略约束。"""
    orch = _orchestration_settings(root)
    if orch.get("use_position_agent", True):
        raw = position_agent_id
    else:
        raw = str(orch.get("worker_terminal_agent") or position_agent_id or "opencode")
    return pick_spawn_agent_id(root, raw)


def _assert_agent_launch_ready(agent_id: str, cfg: dict[str, Any]) -> None:
    """spawn 前检查 npm 包是否完整，避免只弹出空 PowerShell / cmd 窗口。"""
    command = str(cfg.get("command") or "")
    err = agent_launch_check_error(command)
    if err:
        name = cfg.get("name") or agent_id
        raise RuntimeError(f"{name} {err}" if not err.startswith("命令") else err)


def list_agent_tui_status(root: Path) -> list[dict[str, Any]]:
    """列出 agents.yaml 中各 Agent 是否可启动 TUI。"""
    agents = load_agents_config(root).get("agents", {})
    policy = agent_policy(root)
    rows: list[dict[str, Any]] = []
    for agent_id, cfg in agents.items():
        cmd = str(cfg.get("command") or "")
        byok = agent_is_byok(cfg)
        allowed = agent_allowed(root, agent_id)
        rows.append(
            {
                "id": agent_id,
                "name": cfg.get("name", agent_id),
                "command": cmd,
                "byok": byok,
                "allowed": allowed,
                "policy": policy,
                "available": bool(cmd) and agent_available(root, agent_id),
            }
        )
    return rows


def spawn_agent_tui(
    root: Path,
    agent_id: str,
    worktree: Path,
    *,
    title: str,
    prompt: str = "",
    task_id: str = "",
    role: str = "",
    respect_policy: bool = True,
    project_dir: Path | None = None,
) -> None:
    """为新终端窗口启动指定 Agent 的全屏交互 TUI。

    respect_policy=False 时用于 Agent 目录的手动打开（用户自配 API Key，不受 BYOK 策略限制）。
    """
    if respect_policy and not agent_allowed(root, agent_id):
        raise RuntimeError(
            f"Agent {agent_id!r} 在当前策略 {agent_policy(root)!r} 下不可用（需 byok:true 的第三方模型 Agent）"
        )
    spawn_id = agent_id if not respect_policy else pick_spawn_agent_id(root, agent_id)
    cfg = load_agent_config(root, spawn_id)
    _assert_agent_launch_ready(spawn_id, cfg)
    cwd = worktree.resolve()
    task_rel: Path | None = None
    hermes_env: dict[str, str] = {}
    if prompt.strip():
        if project_dir is not None:
            task_body = format_worker_task_prompt(
                project_dir, prompt, task_id=task_id, role=role
            )
        else:
            task_body = format_task_prompt(prompt, task_id=task_id, role=role)
        task_rel = write_task_context_file(cwd, task_body)
        if str(cfg.get("command") or "") == "hermes":
            hermes_env = prepare_hermes_worker_context(
                cwd, task_body, task_id=task_id, task_file_rel=task_rel
            )

    interactive = cfg.get("interactive") if isinstance(cfg.get("interactive"), dict) else {}
    mode = str(interactive.get("mode") or "task_file_context")
    if mode in ("append_system_prompt_file", "prompt_flag") and task_rel is None:
        # 无 prompt 时也写占位，避免 append-system-prompt-file 缺文件
        task_rel = write_task_context_file(
            cwd,
            format_task_prompt(
                "Studio 已为你打开交互会话。请等待主管或 CEO 下达任务。",
                role=role or agent_id,
            ),
        )

    cmd = build_interactive_argv(cfg, task_file_rel=task_rel, worktree=cwd)
    cmd = wrap_argv_for_windows_terminal(cmd, cwd)
    env = agent_subprocess_env()
    env.update(hermes_env)
    spawn_agent_terminal(title, cmd, cwd, env, interactive=True)


def spawn_catalog_command_tui(
    command: str,
    worktree: Path,
    *,
    title: str,
    resolved_path: str | None = None,
) -> None:
    """打开 catalog 中未关联 agents.yaml 的 CLI（如 copilot / kiro-cli）。"""
    command = str(command or "").strip()
    if not command:
        raise RuntimeError("无可用 command")
    err = agent_launch_check_error(command, resolved_path)
    if err:
        raise RuntimeError(err)
    argv = prepare_subprocess_argv([command], interactive=True)
    env = agent_subprocess_env()
    spawn_agent_terminal(title, argv, worktree.resolve(), env, interactive=True)


def spawn_position_tui(
    root: Path,
    project_dir: Path,
    position_id: str,
    worktree: Path,
    *,
    title: str | None = None,
    prompt: str = "",
    task_id: str = "",
) -> None:
    """按岗位配置打开对应 Agent 的 TUI 窗口。"""
    pos = load_position(project_dir, position_id)
    agent_dir = project_dir / "agents" / position_id
    agent_id = str(pos.get("agent") or "opencode")
    spawn_id = resolve_spawn_agent_id(root, agent_id)

    prepare_worker_runtime(root, project_dir, position_id, pos)

    if not agent_available(root, spawn_id):
        write_state(
            agent_dir,
            AgentRuntimeState(
                task_id=task_id,
                status="idle",
                progress=0,
                message=f"Agent {spawn_id} 不可用",
            ),
        )
        raise RuntimeError(f"Agent {spawn_id!r} 不可用")

    window_title = title or f"Studio · {pos.get('name', position_id)} · {pos.get('title', '')}"
    role = f"{pos.get('name', position_id)} ({pos.get('title', '')})".strip()
    spawn_agent_tui(
        root,
        spawn_id,
        worktree,
        title=window_title,
        prompt=prompt,
        task_id=task_id,
        role=role,
        project_dir=project_dir,
    )
    write_state(
        agent_dir,
        AgentRuntimeState(
            task_id=task_id,
            status="working",
            progress=30,
            message=f"{spawn_id} 交互 TUI 已启动",
        ),
    )


# 兼容旧调用名
write_worker_task_file = write_task_context_file


def spawn_worker_agent_terminal(
    root: Path,
    project_dir: Path,
    position_id: str,
    task_description: str,
    worktree: Path,
    *,
    title: str,
    task_id: str = "",
) -> None:
    """编排完成后为岗位 Worker 打开其配置的 Agent TUI。"""
    spawn_position_tui(
        root,
        project_dir,
        position_id,
        worktree,
        title=title,
        prompt=task_description,
        task_id=task_id,
    )
