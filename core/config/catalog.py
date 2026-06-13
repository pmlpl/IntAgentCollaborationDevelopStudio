# core/config/catalog.py — 加载 Agent / 模型选项供 TUI 选择
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_agents(root: Path) -> list[tuple[str, str]]:
    """返回 (显示名, agent_id) 列表；供 Textual Select 使用。"""
    from core.config.agent_policy import list_agents_for_ui

    raw = list_agents_for_ui(root)
    return [(label, aid) for aid, label in raw]


def load_models(root: Path) -> list[tuple[str, str]]:
    """返回 (显示名, model_id) 列表；供 Textual Select 使用。"""
    path = root / "config" / "models.yaml"
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    items: list[tuple[str, str]] = []
    for mid, meta in (data.get("models") or {}).items():
        label = meta.get("name") or mid
        items.append((f"{label} ({mid})", mid))
    return items


def agent_meta(root: Path, agent_id: str) -> dict[str, Any]:
    path = root / "config" / "agents.yaml"
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return (data.get("agents") or {}).get(agent_id, {})
