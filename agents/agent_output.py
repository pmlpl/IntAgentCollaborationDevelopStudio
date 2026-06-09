# agents/agent_output.py — 归一化各 Agent CLI 的 capture 输出为可解析正文
from __future__ import annotations

import json
from typing import Any


def opencode_capture_argv(argv: list[str]) -> list[str]:
    """为 opencode run 插入 --format json，便于从 NDJSON 提取助手正文。"""
    if len(argv) < 2:
        return argv
    if "--format" in argv:
        return argv
    # 逻辑 argv 为 ["opencode","run",...]；Windows 解析后可能是 node+script 或 .exe
    run_idx = next((i for i, part in enumerate(argv) if part == "run"), -1)
    if run_idx < 0:
        return argv
    rest = argv[run_idx + 1 :]
    return [*argv[: run_idx + 1], "--format", "json", *rest]


def _collect_strings(obj: Any, keys: tuple[str, ...] = ("text", "content", "message", "delta")) -> list[str]:
    """递归收集 JSON 事件里可能的文本字段。"""
    found: list[str] = []
    if isinstance(obj, str):
        if obj.strip():
            found.append(obj)
        return found
    if isinstance(obj, dict):
        for key in keys:
            val = obj.get(key)
            if isinstance(val, str) and val.strip():
                found.append(val)
        for val in obj.values():
            found.extend(_collect_strings(val, keys))
        return found
    if isinstance(obj, list):
        for item in obj:
            found.extend(_collect_strings(item, keys))
    return found


def normalize_opencode_capture(raw: str) -> str:
    """将 opencode --format json 的 NDJSON 转为纯文本（保留非 JSON 行）。"""
    if not raw.strip():
        return raw
    parts: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if not stripped.startswith("{"):
            parts.append(stripped)
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            parts.append(stripped)
            continue
        if isinstance(event, dict):
            texts = _collect_strings(event)
            if texts:
                parts.append("".join(texts))
            continue
        parts.append(stripped)
    merged = "\n".join(parts).strip()
    return merged or raw


def normalize_agent_capture(agent_command: str, raw: str) -> str:
    """按 Agent 类型归一化 subprocess 捕获输出。"""
    cmd = (agent_command or "").lower()
    if "opencode" in cmd or cmd == "opencode":
        return normalize_opencode_capture(raw)
    return raw
