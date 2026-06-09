# agents/execute.py — 跨平台 Agent 子进程启动（Windows .cmd/.bat 兼容）
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Sequence


from agents.command_cache import read_shim_text_cached, resolve_agent_command_cached
from agents.goose_env import goose_provider_configured


def _read_shim_text(shim_path: str) -> str:
    return read_shim_text_cached(shim_path)


def _parse_shim_target_exe(shim_path: str) -> str | None:
    """从 shim 文本解析 bin/*.exe 路径（不检查文件是否存在）。"""
    text = _read_shim_text(shim_path)
    if not text:
        return None
    match = re.search(r'node_modules[/\\]([^"\']+\.exe)', text, re.IGNORECASE)
    if not match:
        return None
    base = os.path.dirname(os.path.normpath(shim_path))
    rel = match.group(1).replace("/", os.sep)
    return os.path.normpath(os.path.join(base, "node_modules", rel))


def _resolve_sh_shim_to_exe(shim_path: str) -> str | None:
    """从 npm 的 #!/bin/sh 或 .ps1 shim 中解析出 bin/*.exe 真实路径。"""
    candidate = _parse_shim_target_exe(shim_path)
    if candidate and os.path.isfile(candidate):
        return candidate
    return None


def _resolve_sh_shim_to_node(shim_path: str) -> list[str] | None:
    """从 npm unix shim 解析 node + .js（如 codex.js）。"""
    text = _read_shim_text(shim_path)
    if not text:
        return None
    match = re.search(r'node_modules[/\\]([^"\']+\.js)', text, re.IGNORECASE)
    if not match:
        return None
    base = os.path.dirname(os.path.normpath(shim_path))
    rel = match.group(1).replace("/", os.sep)
    script = os.path.normpath(os.path.join(base, "node_modules", rel))
    if not os.path.isfile(script):
        return None
    node = resolve_agent_command("node")
    if not node:
        return None
    return [node, script]


def _prefer_windows_npm_launcher(command: str, resolved: str) -> str | None:
    """extensionless npm shim 优先解析为 bin/*.exe，其次 .cmd / .ps1。"""
    exe = _resolve_sh_shim_to_exe(resolved)
    if exe:
        return exe
    base = os.path.dirname(os.path.normpath(resolved))
    stem = command.lower()
    for ext in (".cmd", ".CMD", ".ps1"):
        sibling = os.path.join(base, stem + ext)
        if os.path.isfile(sibling):
            return sibling
    return None


def _resolve_agent_command_uncached(command: str) -> str | None:
    """解析 agents.yaml 中的 command 为可执行路径（Windows 上避开不可执行的 unix shim）。"""
    if not command:
        return None
    found = shutil.which(command)
    if not found:
        return None
    if os.name != "nt":
        return found
    found = os.path.normpath(found)
    ext = os.path.splitext(found)[1].lower()
    if ext in ("", ".sh") or _read_shim_text(found).startswith("#!"):
        better = _prefer_windows_npm_launcher(command, found)
        if better:
            return better
    return found


def resolve_agent_command(command: str) -> str | None:
    """带会话缓存的 PATH 解析。"""
    return resolve_agent_command_cached(command)


def agent_command_available(command: str) -> bool:
    """command 是否在 PATH 中可解析。"""
    return resolve_agent_command(command) is not None


def agent_subprocess_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """子进程环境：强制 UTF-8，避免 Windows 默认 GBK 解码 Agent 输出失败。"""
    env = (base or os.environ).copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    return env


# 捕获 stdout/stderr 时的统一参数（Windows 上必须显式 utf-8，否则 text=True 用 GBK）
CAPTURE_TEXT_KW: dict[str, Any] = {
    "capture_output": True,
    "text": True,
    "encoding": "utf-8",
    "errors": "replace",
}


def _resolve_cmd_shim_to_exe(shim_path: str) -> str | None:
    """将 npm 等 .cmd/.bat 启动脚本解析为真实 .exe，避免 cmd.exe /c 拆参截断长 prompt。"""
    shim_path = os.path.normpath(shim_path)
    base = os.path.dirname(shim_path)
    name = os.path.basename(shim_path).lower()

    # npm 全局 claude：claude / claude.cmd / claude.ps1 → claude.exe
    if name in ("claude.cmd", "claude.bat", "claude", "claude.ps1"):
        candidate = os.path.join(
            base,
            "node_modules",
            "@anthropic-ai",
            "claude-code",
            "bin",
            "claude.exe",
        )
        if os.path.isfile(candidate):
            return candidate

    # 通用：解析 batch / ps1 中 "%dp0%\\path\\to\\tool.exe" 或 node_modules/.../bin/*.exe
    text = _read_shim_text(shim_path)
    if not text:
        return None
    parsed = _resolve_sh_shim_to_exe(shim_path)
    if parsed:
        return parsed
    match = re.search(r'["\']?%dp0%\\([^"\r\n\'>]+\.exe)["\']?', text, re.IGNORECASE)
    if not match:
        return None
    rel = match.group(1).replace("\\", os.sep)
    candidate = os.path.normpath(os.path.join(base, rel))
    if os.path.isfile(candidate):
        return candidate
    return None


def _resolve_cmd_shim_to_node(shim_path: str) -> list[str] | None:
    """解析 npm .cmd 中 node "%dp0%\\..." 模式，返回 [node.exe, script.js, ...]。"""
    shim_path = os.path.normpath(shim_path)
    try:
        text = Path(shim_path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    match = re.search(
        r'node(?:\.exe)?\s+"%dp0%\\([^"]+)"',
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    base = os.path.dirname(shim_path)
    rel = match.group(1).replace("\\", os.sep)
    script = os.path.normpath(os.path.join(base, rel))
    if not os.path.isfile(script):
        return None
    node = resolve_agent_command("node")
    if not node:
        return None
    return [node, script]


def _is_batch_shim(path: str) -> bool:
    """判断无扩展名的 npm 全局命令是否为 batch/node 启动脚本。"""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="ignore")[:512].lower()
    except OSError:
        return False
    return "@echo" in text or "%dp0%" in text or "node" in text


def _resolve_windows_shim(
    resolved: str,
    rest: list[str],
    *,
    interactive: bool,
) -> list[str] | None:
    """解析 Windows 下 .cmd / 无扩展名 npm shim → .exe、node 脚本或 cmd /k。"""
    candidates = [resolved]
    if os.path.splitext(resolved)[1].lower() not in (".cmd", ".bat"):
        candidates.append(resolved + ".cmd")

    for path in candidates:
        if not os.path.isfile(path):
            continue
        ext = os.path.splitext(path)[1].lower()
        is_shim = ext in (".cmd", ".bat") or _is_batch_shim(path)
        if ext == ".exe":
            return [path, *rest]
        if not is_shim:
            continue

        native = _resolve_cmd_shim_to_exe(path)
        if native:
            return [native, *rest]
        node_argv = _resolve_cmd_shim_to_node(path)
        if node_argv:
            return [*node_argv, *rest]
        if interactive:
            return ["cmd.exe", "/k", path, *rest]
        line = subprocess.list2cmdline([path, *rest])
        return ["cmd.exe", "/c", line]
    return None


def prepare_subprocess_argv(
    argv: Sequence[str],
    *,
    interactive: bool = False,
) -> list[str]:
    """构建 subprocess 可用 argv；Windows 下 .cmd/.bat 优先解析为原生 .exe 或 node 脚本。

    interactive=True 时 .cmd 用 cmd /k 保持 TTY，避免 TUI 秒退后只剩空 shell。
    """
    if not argv:
        raise ValueError("empty command argv")
    name = argv[0]
    resolved = resolve_agent_command(name) or name
    rest = list(argv[1:])

    if os.name == "nt":
        ext = os.path.splitext(resolved)[1].lower()
        if ext == ".ps1":
            invocation = subprocess.list2cmdline([resolved, *rest])
            return [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                *(["-NoExit"] if interactive else []),
                "-Command",
                f"& {invocation}",
            ]
        shim_argv = _resolve_windows_shim(resolved, rest, interactive=interactive)
        if shim_argv:
            return shim_argv
        # unix shim 仅有 .js 入口（如 codex）
        if _read_shim_text(resolved).startswith("#!"):
            node_argv = _resolve_sh_shim_to_node(resolved)
            if node_argv:
                return [*node_argv, *rest]
        if os.path.isfile(resolved):
            return [resolved, *rest]

    if os.path.isfile(resolved):
        return [resolved, *rest]
    found = resolve_agent_command(name)
    if found:
        return prepare_subprocess_argv([found, *rest], interactive=interactive)
    return [name, *rest]


def agent_launch_check_error(command: str, resolved: str | None = None) -> str:
    """检查 Agent 是否可真正启动 TUI；空字符串表示 OK。"""
    command = str(command or "").strip()
    if command == "goose" and not goose_provider_configured():
        path = resolved if resolved is not None else resolve_agent_command(command)
        if path:
            return (
                "需先运行 goose configure 配置 model provider。"
                "在 Agent 目录双击此项可自动打开配置向导"
            )

    path = resolved if resolved is not None else resolve_agent_command(command)
    if not path:
        return f"命令 {command!r} 不在 PATH 中"

    # 与真正 spawn 相同的路径解析；能解析即视为可启动（避免误报「需补装」）
    try:
        prepare_subprocess_argv([command, "--version"], interactive=False)
    except ValueError:
        return f"命令 {command!r} 无法解析为可执行程序"
    return ""
