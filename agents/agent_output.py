# agents/agent_output.py — 归一化各 Agent CLI 的 capture 输出为可解析正文
from __future__ import annotations

import json
import re
from typing import Any

# ANSI escape sequence pattern (SGR/CSI codes used for colors, cursor positioning, etc.)
_ANSI_RE = re.compile(r"\x1b\[[0-9;:]*[A-Za-z]")
# Hermes box-drawing characters used in TUI border
_HERMES_BORDER_CHARS = set("─═╔╗╚╝║┌┐└┘├┤┬┴┼╭╮╰╯")


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from text."""
    return _ANSI_RE.sub("", text)


def _strip_hermes_formatting(text: str) -> str:
    """Strip Hermes TUI formatting: ANSI codes + box-drawing borders.

    Hermes v0.16.0 chat -q still emits TUI decorations (colored box,
    ANSI escape codes).  The TUI box also wraps multi-line JSON across
    several lines, so we reconstruct contiguous JSON blocks.
    """
    # 1) Strip ANSI escape codes
    cleaned = _ANSI_RE.sub("", text)
    # 2) Remove lines that are mostly box-drawing characters
    lines = cleaned.splitlines()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        char_count = sum(1 for c in stripped if c not in (" ", "\t"))
        border_count = sum(1 for c in stripped if c in _HERMES_BORDER_CHARS)
        if border_count > 0 and border_count >= char_count * 0.5:
            continue
        out.append(line)
    result = "\n".join(out)

    # 3) Reconstruct multi-line JSON fragments after the LAST STUDIO marker.
    #    Hermes wraps the JSON inside a fixed-width TUI box, so the text
    #    can be split across several lines with leading whitespace.
    #    We target the LAST marker because parse_manager_output /
    #    parse_manager_review_output both use split(MARKER)[-1] — earlier
    #    markers are from the prompt (example JSON), not the agent response.
    import re as _re

    _marker_pat = _re.compile(r"---STUDIO_[A-Z_]+_JSON---")
    matches = list(_marker_pat.finditer(result))
    if not matches:
        return result.strip()

    # Process only the last marker (the agent's actual output)
    m = matches[-1]
    marker = m.group()
    after = result[m.end() :]
    # Find JSON start: array [{ or object {
    json_start = -1
    for prefix in ("[{", "{"):
        pos = after.find(prefix)
        if pos >= 0 and (json_start < 0 or pos < json_start):
            json_start = pos
    if json_start >= 0:
        json_part = after[json_start:]
        # Collapse multi-line JSON: join lines, strip leading whitespace
        json_lines = json_part.splitlines()
        joined = "".join(line.strip() for line in json_lines)
        # Find matching closing bracket
        depth = 0
        end_idx = -1
        brackets = {"[": "]", "{": "}"}
        for i, c in enumerate(joined):
            if c in brackets:
                depth += 1
            elif c in ("]", "}"):
                depth -= 1
                if depth == 0:
                    end_idx = i + 1
                    break
        if end_idx > 0:
            json_block = joined[:end_idx]
            result = result[: m.start()] + marker + "\n" + json_block + result[m.end() + json_start + end_idx:]
    return result.strip()


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
    if "hermes" in cmd or cmd == "hermes":
        return _strip_hermes_formatting(raw)
    # Generic: strip ANSI for all agents (harmless if none present)
    return _strip_ansi(raw)
