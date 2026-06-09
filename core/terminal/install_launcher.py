# core/terminal/install_launcher.py — 在终端中执行 Agent 官方安装命令
from __future__ import annotations

import os
import re
from pathlib import Path

from agents.execute import agent_subprocess_env
from core.terminal.spawner import spawn_agent_terminal


def is_runnable_install_cmd(install_cmd: str) -> bool:
    """是否可在终端直接执行的安装/配置命令（npm / pip / goose configure 等）。"""
    cmd = install_cmd.strip()
    if not cmd:
        return False
    if cmd.startswith("见 ") or "docs/" in cmd:
        return False
    if re.match(r"^goose\s+configure$", cmd, re.IGNORECASE):
        return True
    return bool(
        re.match(
            r"^(npm|pip3?|pnpm|yarn|powershell|pwsh|gh)\s+",
            cmd,
            re.IGNORECASE,
        )
    )


def spawn_install_terminal(
    title: str,
    install_cmd: str,
    cwd: Path,
) -> None:
    """新开终端并执行安装命令（cmd /k 保持窗口，便于查看输出）。"""
    cmd = install_cmd.strip()
    if not is_runnable_install_cmd(cmd):
        raise RuntimeError(f"无法自动执行安装命令: {cmd}")

    if os.name == "nt":
        argv = ["cmd.exe", "/k", cmd]
    else:
        argv = ["bash", "-lc", cmd]

    env = agent_subprocess_env()
    spawn_agent_terminal(title, argv, cwd.resolve(), env, interactive=True)
