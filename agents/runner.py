# agents/runner.py — 统一执行岗位 Agent 任务
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import yaml

from agents.execute import (
    CAPTURE_TEXT_KW,
    agent_command_available,
    agent_subprocess_env,
    prepare_subprocess_argv,
)
from agents.agent_output import normalize_agent_capture, opencode_capture_argv
from agents.registry import build_command, load_agent_config
from core.dispatch.decompose import MARKER, generate_mock_subtasks
from core.logging import get_logger
from core.platform.skills_client import prepare_worker_runtime
from core.runtime.state import AgentRuntimeState, write_state

logger = get_logger(__name__)


def load_position(project_dir: Path, position_id: str) -> dict[str, Any]:
    data = yaml.safe_load((project_dir / "positions.yaml").read_text(encoding="utf-8"))
    for pos in data.get("positions", []):
        if pos["id"] == position_id:
            return pos
    raise KeyError(f"position not found: {position_id}")


def agent_available(root: Path, agent_key: str) -> bool:
    try:
        cfg = load_agent_config(root, agent_key)
    except KeyError:
        return False
    cmd = cfg.get("command", "")
    return bool(cmd) and agent_command_available(cmd)


def run_position_task(
    root: Path,
    project_dir: Path,
    position_id: str,
    task_description: str,
    worktree: Path | None = None,
    *,
    mock: bool = False,
) -> int:
    """加载岗位配置，构建命令，更新 state，执行 subprocess。"""
    pos = load_position(project_dir, position_id)
    agent_dir = project_dir / "agents" / position_id
    cwd = worktree or project_dir

    # 防线一：解析 resume.skills，写入 runtime/skills.manifest.yaml
    skills, mcp_servers = prepare_worker_runtime(root, project_dir, position_id, pos)

    write_state(
        agent_dir,
        AgentRuntimeState(
            status="working",
            progress=10,
            message="正在执行…",
        ),
    )

    if mock or not agent_available(root, pos["agent"]):
        logger.info("position %s: mock mode (mock=%s agent_available=%s)", position_id, mock, agent_available(root, pos["agent"]))
        write_state(
            agent_dir,
            AgentRuntimeState(status="submitted", progress=100, message="mock 完成"),
        )
        return 0

    cfg = load_agent_config(root, pos["agent"])
    cmd = prepare_subprocess_argv(
        build_command(
            cfg,
            task=task_description,
            worktree=cwd,
            skills=skills,
            mcp_servers=mcp_servers,
        )
    )
    logger.info("position %s: spawning subprocess %s in %s", position_id, cmd, cwd)
    env = agent_subprocess_env()
    try:
        result = subprocess.run(cmd, cwd=cwd, env=env)
    except FileNotFoundError as exc:
        logger.error("position %s: agent CLI not found: %s", position_id, exc)
        write_state(
            agent_dir,
            AgentRuntimeState(
                status="idle",
                progress=0,
                message=f"无法启动 Agent: {exc}",
            ),
        )
        raise
    status = "submitted" if result.returncode == 0 else "idle"
    write_state(
        agent_dir,
        AgentRuntimeState(
            status=status,
            progress=100 if result.returncode == 0 else 0,
            message="已完成" if result.returncode == 0 else f"退出码 {result.returncode}",
        ),
    )
    return result.returncode


def _agent_task_timeout(root: Path, task_type: str = "default") -> int:
    """从 platform config 读取 Agent 任务超时（秒）；未配置时用合理默认值。"""
    try:
        data = yaml.safe_load((root / "config" / "platform.yaml").read_text(encoding="utf-8")) or {}
    except Exception:
        return 180 if task_type == "decompose" else 120
    orch = data.get("orchestration") or {}
    key = f"timeout_{task_type}" if task_type in ("decompose", "research", "review") else "timeout_agent"
    val = orch.get(key)
    if isinstance(val, (int, float)) and val > 0:
        return int(val)
    if task_type == "decompose":
        return 300  # complex decomposition needs more time with slower models
    if task_type == "research":
        return 180
    return 120


def run_position_task_capture(
    root: Path,
    project_dir: Path,
    position_id: str,
    task_description: str,
    worktree: Path | None = None,
    *,
    mock: bool = False,
    timeout_sec: int | None = None,
) -> tuple[int, str]:
    """执行任务并捕获 stdout/stderr，供主管拆解解析。

    支持超时 → 优雅降级；超时后写 state 为 idle 并返回错误信息。
    """
    pos = load_position(project_dir, position_id)
    agent_dir = project_dir / "agents" / position_id
    cwd = worktree or project_dir
    timeout = timeout_sec if timeout_sec is not None else _agent_task_timeout(root, "decompose")

    skills, mcp_servers = prepare_worker_runtime(root, project_dir, position_id, pos)

    write_state(
        agent_dir,
        AgentRuntimeState(status="working", progress=10, message="正在执行…"),
    )

    if mock or not agent_available(root, pos["agent"]):
        import json

        output = f"{MARKER}\n" + json.dumps(
            generate_mock_subtasks(project_dir, task_description),
            ensure_ascii=False,
            indent=2,
        )
        write_state(
            agent_dir,
            AgentRuntimeState(status="submitted", progress=100, message="mock 完成"),
        )
        return 0, output

    cfg = load_agent_config(root, pos["agent"])
    agent_id = str(pos.get("agent") or "")
    agent_command = str(cfg.get("command") or "")
    logical = build_command(
        cfg,
        task=task_description,
        worktree=cwd,
        skills=skills,
        mcp_servers=mcp_servers,
        agent_id=agent_id,
    )
    if agent_command == "opencode":
        logical = opencode_capture_argv(logical)
    cmd = prepare_subprocess_argv(logical)
    env = agent_subprocess_env()

    # 保存原始输出到日志（含诊断信息）
    log_path = agent_dir / "runtime" / "last_output.txt"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        result = subprocess.run(cmd, cwd=cwd, env=env, timeout=timeout, **CAPTURE_TEXT_KW)
    except subprocess.TimeoutExpired as exc:
        partial_stdout = (exc.stdout or b"").decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        partial_stderr = (exc.stderr or b"").decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        partial = (partial_stdout + "\n" + partial_stderr).strip()
        msg = f"Agent 执行超时（>{timeout}s）"
        logger.error("position %s: %s (partial=%d chars)", position_id, msg, len(partial))
        log_path.write_text(
            f"[TIMEOUT] {msg}\n--- partial stdout/stderr ({len(partial)} chars) ---\n{partial[:4000]}\n",
            encoding="utf-8",
        )
        # If we have partial output, try to use it (the marker/JSON might be in there)
        if partial:
            normalized = normalize_agent_capture(agent_command, partial)
            if len(normalized) > 50:
                write_state(
                    agent_dir,
                    AgentRuntimeState(status="submitted", progress=95, message="超时但有输出，尝试解析"),
                )
                return 0, normalized
        write_state(
            agent_dir,
            AgentRuntimeState(status="idle", progress=0, message=msg),
        )
        return 1, msg
    except FileNotFoundError as exc:
        msg = f"无法启动 Agent CLI: {exc}"
        logger.error("position %s: %s", position_id, msg)
        log_path.write_text(f"[ERROR] {msg}\n", encoding="utf-8")
        write_state(
            agent_dir,
            AgentRuntimeState(status="idle", progress=0, message=msg),
        )
        return 1, msg
    except OSError as exc:
        msg = f"Agent 子进程 OS 错误: {exc}"
        logger.error("position %s: %s", position_id, msg)
        log_path.write_text(f"[ERROR] {msg}\n", encoding="utf-8")
        write_state(
            agent_dir,
            AgentRuntimeState(status="idle", progress=0, message=msg),
        )
        return 1, msg

    raw = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
    output = normalize_agent_capture(agent_command, raw)
    log_path.write_text(f"--- rc={result.returncode} ---\n{output}", encoding="utf-8")

    # 检查常见 Agent 错误模式
    lowered = output.lower()
    if "api key" in lowered or "unauthorized" in lowered:
        msg = "Agent 执行失败：API key 未配置或无效"
        write_state(agent_dir, AgentRuntimeState(status="idle", progress=0, message=msg))
        return 1, msg

    status = "submitted" if result.returncode == 0 else "idle"
    write_state(
        agent_dir,
        AgentRuntimeState(
            status=status,
            progress=100 if result.returncode == 0 else 0,
            message="已完成" if result.returncode == 0 else f"退出码 {result.returncode}",
        ),
    )
    return result.returncode, output


def run_agent_prompt_capture(
    root: Path,
    agent_key: str,
    prompt: str,
    cwd: Path | None = None,
    *,
    timeout_sec: int | None = None,
) -> tuple[int, str]:
    """直接调用指定 Agent 执行 prompt 并捕获输出（供调研 Agent 等使用）。"""
    workdir = cwd or root
    if not agent_available(root, agent_key):
        return 1, f"Agent {agent_key!r} 不可用（CLI 未安装或不在 PATH）"

    timeout = timeout_sec if timeout_sec is not None else _agent_task_timeout(root, "research")

    cfg = load_agent_config(root, agent_key)
    agent_command = str(cfg.get("command") or "")
    logical = build_command(
        cfg, task=prompt, worktree=workdir, agent_id=agent_key
    )
    if agent_command == "opencode":
        logical = opencode_capture_argv(logical)
    cmd = prepare_subprocess_argv(logical)
    env = agent_subprocess_env()
    try:
        result = subprocess.run(cmd, cwd=workdir, env=env, timeout=timeout, **CAPTURE_TEXT_KW)
    except subprocess.TimeoutExpired:
        msg = f"Agent {agent_key!r} 执行超时（>{timeout}s）"
        logger.error("run_agent_prompt_capture: %s", msg)
        return 1, msg
    except FileNotFoundError as exc:
        return 1, f"无法启动 Agent CLI: {exc}"
    except OSError as exc:
        return 1, f"Agent 子进程 OS 错误: {exc}"
    raw = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
    output = normalize_agent_capture(agent_command, raw)
    log_dir = root / ".studio" / "research"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "last_agent_output.txt").write_text(output, encoding="utf-8")

    # 保存原始输出用于诊断
    (log_dir / "last_agent_raw.txt").write_text(raw, encoding="utf-8")
    return result.returncode, output
