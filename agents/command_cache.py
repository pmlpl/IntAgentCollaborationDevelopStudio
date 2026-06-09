# agents/command_cache.py — Agent 命令解析缓存（避免重复 which / 读 shim）
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


# shim 文件内容缓存：(path -> (mtime, text))
_shim_text_cache: dict[str, tuple[float, str]] = {}


def read_shim_text_cached(shim_path: str) -> str:
    """按 mtime 缓存 npm shim 文本，避免同一路径重复读盘。"""
    path = os.path.normpath(shim_path)
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return ""
    hit = _shim_text_cache.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        text = Path(path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        text = ""
    _shim_text_cache[path] = (mtime, text)
    return text


def clear_agent_command_cache() -> None:
    """安装/卸载 Agent 后清缓存（如 Agent 目录点「刷新」）。"""
    _shim_text_cache.clear()
    _resolve_agent_command_cached.cache_clear()


@lru_cache(maxsize=64)
def _resolve_agent_command_cached(command: str) -> str | None:
    """内部：带 lru 的 PATH 解析（见 execute.resolve_agent_command）。"""
    from agents.execute import _resolve_agent_command_uncached

    return _resolve_agent_command_uncached(command)


def resolve_agent_command_cached(command: str) -> str | None:
    """对外：缓存版 resolve。"""
    if not command:
        return None
    return _resolve_agent_command_cached(command.strip())
