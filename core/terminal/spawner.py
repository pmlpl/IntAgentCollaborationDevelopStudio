# core/terminal/spawner.py — 在新终端窗口启动 Agent 命令
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from core.supervisor_client import SupervisorClient

TerminalKind = Literal["wt", "cmd"]


def find_terminal() -> TerminalKind | str:
    """优先 Windows Terminal；非 Windows 预留接口（Phase 1.5 未实现）。"""
    if os.name == "nt":
        if shutil.which("wt.exe"):
            return "wt"
        return "cmd"
    if shutil.which("gnome-terminal"):
        return "gnome-terminal"
    if sys.platform == "darwin":
        return "osascript"
    return "cmd"


def build_spawn_command(
    command: list[str],
    cwd: Path,
    title: str = "Studio Agent",
    *,
    interactive: bool = False,
) -> list[str]:
    """构建启动新终端窗口的命令行。

    interactive=True 时保持 TTY；Windows Terminal 下直接把 argv 交给 wt，避免 cmd /k 套 cmd /c 导致 TUI 秒退。
    """
    cwd = cwd.resolve()
    kind = find_terminal()
    if kind == "wt":
        if interactive:
            # wt 直接执行 claude.exe / cmd /k xxx.cmd / node script，不再外包一层 cmd /k
            return [
                "wt.exe",
                "new-tab",
                "-d",
                str(cwd),
                "--title",
                title,
                "--",
                *command,
            ]
        inner = subprocess.list2cmdline(command) + " & pause"
        return [
            "wt.exe",
            "new-tab",
            "-d",
            str(cwd),
            "--title",
            title,
            "--",
            "cmd",
            "/c",
            inner,
        ]
    if interactive:
        # 无 wt 时：若已是 cmd /k，直接 start；否则 cmd /k 包裹
        if (
            command
            and os.path.basename(command[0]).lower() == "cmd.exe"
            and len(command) >= 2
            and command[1].lower() == "/k"
        ):
            return ["cmd.exe", "/c", "start", title, *command]
        inner = subprocess.list2cmdline(command)
        return ["cmd.exe", "/c", "start", title, "cmd", "/k", inner]
    inner = subprocess.list2cmdline(command)
    return ["cmd.exe", "/c", "start", title, "cmd", "/k", inner]


def spawn_agent_terminal(
    title: str,
    command: list[str],
    cwd: Path,
    env: dict[str, str] | None = None,
    *,
    interactive: bool = False,
) -> subprocess.Popen:
    """在新终端窗口启动 Agent，不阻塞调用方。"""
    spawn_cmd = build_spawn_command(
        command, cwd, title=title, interactive=interactive
    )
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.Popen(
        spawn_cmd,
        cwd=cwd,
        env=merged,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )


def spawn_python_module(
    title: str,
    module_args: list[str],
    cwd: Path,
    env: dict[str, str] | None = None,
    *,
    supervisor: SupervisorClient | None = None,
    position_id: str | None = None,
    project_id: str = "",
) -> subprocess.Popen:
    """在新终端窗口运行 python -m ...（始终弹出可见终端）。"""
    _ = supervisor, position_id, project_id  # 保留参数供后续 PID 注册扩展
    cmd = [sys.executable, "-m", *module_args]
    return spawn_agent_terminal(title, cmd, cwd, env)
