# cli/relay_agent.py — Windows 终端启动中继：从 JSON 读取 argv，避免长 prompt 被拆参
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def argv_needs_relay(argv: list[str]) -> bool:
    """参数是否可能在 wt/cmd 传参时被拆碎（多行、引号、较长文本）。"""
    if os.name != "nt":
        return False
    for part in argv[1:]:
        text = str(part)
        if len(text) > 120 or "\n" in text or "\r" in text or '"' in text or "{" in text:
            return True
    return False


def wrap_argv_for_windows_terminal(argv: list[str], cwd: Path) -> list[str]:
    """将 Agent argv 写入 JSON，由本模块原样 subprocess 启动。"""
    if not argv_needs_relay(argv):
        return argv
    path = (cwd / ".studio" / "_spawn_argv.json").resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(argv, ensure_ascii=False), encoding="utf-8")
    return [sys.executable, "-m", "cli.relay_agent", str(path)]


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("usage: python -m cli.relay_agent <argv.json>", file=sys.stderr)
        return 2
    path = Path(args[0])
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"relay_agent: 无法读取 {path}: {exc}", file=sys.stderr)
        return 2
    if not isinstance(payload, list) or not payload:
        print("relay_agent: argv.json 必须是非空 JSON 数组", file=sys.stderr)
        return 2
    command = [str(x) for x in payload]
    return int(subprocess.call(command))


if __name__ == "__main__":
    raise SystemExit(main())
