# core/config/catalog.py — 加载 Agent / 模型选项供 TUI 选择
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_agents(root: Path) -> list[tuple[str, str]]:
    """返回 (agent_id, 显示名) 列表；受 platform agents.policy 过滤。"""
    from core.config.agent_policy import list_agents_for_ui

    return list_agents_for_ui(root)


def load_models(root: Path) -> list[tuple[str, str]]:
    """返回 (model_id, 显示名) 列表。"""
    path = root / "config" / "models.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    items: list[tuple[str, str]] = []
    for mid, meta in (data.get("models") or {}).items():
        label = meta.get("name") or mid
        items.append((mid, f"{label} ({mid})"))
    return items


def agent_meta(root: Path, agent_id: str) -> dict[str, Any]:
    path = root / "config" / "agents.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return (data.get("agents") or {}).get(agent_id, {})
