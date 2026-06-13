# agents/health.py — Agent 健康检查：验证 CLI 可执行、有 API key、可产出有效输出
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from agents.execute import (
    CAPTURE_TEXT_KW,
    agent_command_available,
    agent_subprocess_env,
    prepare_subprocess_argv,
)
from agents.registry import load_agent_config
from core.logging import get_logger

logger = get_logger(__name__)

VERSION_TIMEOUT = 15  # seconds for --version check
SMOKE_TIMEOUT = 30    # seconds for smoke test
SMOKE_PROMPT = "Reply with exactly: OK"


@dataclass
class AgentHealthReport:
    """Agent 健康检查报告。"""

    agent_id: str
    command: str = ""
    resolved_path: str = ""
    available: bool = False
    version: str = ""
    version_ok: bool = False
    version_error: str = ""
    smoke_ok: bool = False
    smoke_output: str = ""
    smoke_error: str = ""
    smoke_rc: int = -1
    api_key_ok: bool | None = None  # None = 无法判断
    checks: list[dict[str, Any]] = field(default_factory=list)
    overall: str = "unknown"  # ok | degraded | unavailable

    @property
    def healthy(self) -> bool:
        return self.overall == "ok"


def check_command_exists(command: str) -> tuple[bool, str]:
    """检查命令是否可解析且在 PATH 中。"""
    from agents.execute import resolve_agent_command

    resolved = resolve_agent_command(command)
    if not resolved:
        return False, f"命令 {command!r} 不在 PATH 中"
    return True, resolved


def check_version(command: str, resolved_path: str, agent_id: str = "") -> tuple[bool, str, str]:
    """运行 --version 检查 Agent CLI 是否能启动。"""
    try:
        argv = prepare_subprocess_argv([command, "--version"], interactive=False)
    except ValueError as exc:
        return False, "", f"无法构建 argv: {exc}"

    env = agent_subprocess_env()
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=VERSION_TIMEOUT,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return False, "", f"--version 超时（>{VERSION_TIMEOUT}s）"
    except FileNotFoundError:
        return False, "", f"可执行文件未找到: {resolved_path}"
    except OSError as exc:
        return False, "", f"OS 错误: {exc}"

    output = (result.stdout or "") + (result.stderr or "")
    if not output.strip():
        return False, "", "无输出（可能未配置或缺少依赖）"

    # 检查常见错误模式
    lowered = output.lower()
    if "api key" in lowered or "apikey" in lowered or "unauthorized" in lowered:
        return False, output.strip()[:200], "API key 未配置或无效"
    if "command not found" in lowered:
        return False, output.strip()[:200], "命令未找到"

    return True, output.strip()[:500], ""


def check_smoke(
    command: str,
    resolved_path: str,
    agent_id: str = "",
    cwd: Path | None = None,
) -> tuple[bool, str, int, str]:
    """快速冒烟：发送简单 prompt，验证 Agent 能否产出有效输出。"""
    from agents.agent_output import normalize_agent_capture, opencode_capture_argv
    from agents.registry import build_command, load_agent_config

    workdir = cwd or Path.cwd()
    root = _find_studio_root(workdir)

    try:
        cfg = load_agent_config(root, agent_id or command)
    except KeyError:
        return False, "", -1, f"Agent {agent_id!r} 不在 agents.yaml 中"

    logical = build_command(
        cfg,
        task=SMOKE_PROMPT,
        worktree=workdir,
        agent_id=agent_id,
    )
    if command == "opencode" or "opencode" in str(cfg.get("command", "")):
        logical = opencode_capture_argv(logical)

    try:
        argv = prepare_subprocess_argv(logical, interactive=False)
    except ValueError as exc:
        return False, "", -1, f"无法构建 argv: {exc}"

    env = agent_subprocess_env()
    try:
        result = subprocess.run(
            argv,
            cwd=workdir,
            env=env,
            timeout=SMOKE_TIMEOUT,
            **CAPTURE_TEXT_KW,
        )
    except subprocess.TimeoutExpired:
        return False, "", -1, f"冒烟测试超时（>{SMOKE_TIMEOUT}s）"
    except FileNotFoundError:
        return False, "", -1, f"可执行文件未找到: {resolved_path}"
    except OSError as exc:
        return False, "", -1, f"OS 错误: {exc}"

    raw = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
    output = normalize_agent_capture(command, raw)

    # 分析输出判断是否可用
    lowered = output.lower()
    if "api key" in lowered or "unauthorized" in lowered or "authentication" in lowered:
        return False, output.strip()[:400], result.returncode, "API key 未配置或无效"

    if result.returncode != 0:
        return False, output.strip()[:400], result.returncode, f"退出码 {result.returncode}"

    return True, output.strip()[:400], result.returncode, ""


def check_agent(
    root: Path,
    agent_id: str,
    *,
    smoke: bool = False,
    cwd: Path | None = None,
) -> AgentHealthReport:
    """对单个 Agent 执行完整健康检查。

    检查项：
    1. 命令是否在 PATH
    2. --version 是否正常启动
    3. （可选）冒烟 prompt → 是否产出有效输出
    """
    try:
        cfg = load_agent_config(root, agent_id)
    except KeyError:
        return AgentHealthReport(
            agent_id=agent_id,
            overall="unavailable",
            checks=[{"check": "config", "ok": False, "detail": f"Agent {agent_id!r} 不在 agents.yaml 中"}],
        )

    command = str(cfg.get("command", ""))
    if not command:
        return AgentHealthReport(
            agent_id=agent_id,
            overall="unavailable",
            checks=[{"check": "config", "ok": False, "detail": "未配置 command"}],
        )

    report = AgentHealthReport(agent_id=agent_id, command=command)
    report.checks = []

    # Check 1: PATH
    ok, detail = check_command_exists(command)
    report.available = ok
    report.resolved_path = detail if ok else ""
    report.checks.append({"check": "path", "ok": ok, "detail": detail})
    if not ok:
        report.overall = "unavailable"
        return report

    # Check 2: --version
    ok, version_text, err = check_version(command, report.resolved_path, agent_id)
    report.version_ok = ok
    report.version = version_text
    report.version_error = err
    report.checks.append({
        "check": "version",
        "ok": ok,
        "detail": version_text[:200] if ok else err,
    })

    # 从 version 输出推断 API key 状态
    combined = (version_text + " " + err).lower()
    if "api key" in combined or "unauthorized" in combined:
        report.api_key_ok = False

    # Check 3: Smoke (optional)
    if smoke:
        ok, output, rc, err = check_smoke(command, report.resolved_path, agent_id, cwd)
        report.smoke_ok = ok
        report.smoke_output = output
        report.smoke_rc = rc
        report.smoke_error = err
        report.checks.append({
            "check": "smoke",
            "ok": ok,
            "detail": f"rc={rc}, output={output[:120]}" if output else err,
        })

    # Determine overall status
    if report.version_ok:
        report.overall = "ok"
    elif report.available:
        report.overall = "degraded"
    else:
        report.overall = "unavailable"

    return report


def check_all_agents(
    root: Path,
    *,
    smoke: bool = False,
    cwd: Path | None = None,
) -> dict[str, AgentHealthReport]:
    """检查 agents.yaml 中所有已启用的 Agent。"""
    from core.config.agent_policy import agent_enabled

    data = yaml.safe_load((root / "config" / "agents.yaml").read_text(encoding="utf-8"))
    agents = data.get("agents", {})

    results: dict[str, AgentHealthReport] = {}
    for agent_id in sorted(agents):
        if not agent_enabled(root, agent_id):
            continue
        results[agent_id] = check_agent(root, agent_id, smoke=smoke, cwd=cwd)
    return results


def _find_studio_root(path: Path) -> Path:
    """从当前目录向上找 studio 根目录。"""
    for p in [path] + list(path.parents):
        if (p / "config" / "platform.yaml").exists():
            return p
    return path
