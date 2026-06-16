# core/config/platform_settings.py — platform.yaml 常用读取函数
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def get_orchestration_settings(root: Path) -> dict[str, Any]:
    """读取 platform.yaml 中的 orchestration 段，供 dispatcher / agent_launcher 共用。"""
    path = root / "config" / "platform.yaml"
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    orch = data.get("orchestration")
    return orch if isinstance(orch, dict) else {}
