# core/org/persist.py — 组织树读写与变更快照
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from core.org.tree_ops import OrgTree, OrgTreeError


def load_positions_data(project_dir: Path) -> dict[str, Any]:
    """读取 positions.yaml。"""
    path = project_dir / "positions.yaml"
    if not path.exists():
        raise FileNotFoundError(f"positions.yaml not found: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def save_positions_data(project_dir: Path, data: dict[str, Any], *, reason: str = "") -> Path:
    """校验并写入 positions.yaml，追加 org.snapshot 审计。"""
    OrgTree.from_yaml_data(data)
    path = project_dir / "positions.yaml"
    path.write_text(yaml.dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    _append_snapshot(project_dir, data, reason=reason)
    return path


def _append_snapshot(project_dir: Path, data: dict[str, Any], *, reason: str) -> None:
    snap_path = project_dir / "org.snapshot.yaml"
    history: list[dict[str, Any]] = []
    if snap_path.exists():
        raw = yaml.safe_load(snap_path.read_text(encoding="utf-8")) or {}
        history = list(raw.get("history") or [])
    history.append(
        {
            "at": datetime.now(timezone.utc).isoformat(),
            "reason": reason or "update",
            "positions": deepcopy(data.get("positions", [])),
        }
    )
    snap_path.write_text(
        yaml.dump({"history": history[-20:]}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def ensure_agent_sandbox(project_dir: Path, position_id: str) -> Path:
    """为新岗位创建 agents/{id}/ 沙箱目录。"""
    agent_dir = project_dir / "agents" / position_id
    (agent_dir / "runtime").mkdir(parents=True, exist_ok=True)
    (agent_dir / "cache").mkdir(exist_ok=True)
    (agent_dir / "logs").mkdir(exist_ok=True)
    (agent_dir / "inbox" / "processed").mkdir(parents=True, exist_ok=True)
    return agent_dir


def apply_tree(project_dir: Path, tree: OrgTree, meta: dict[str, Any], *, reason: str) -> Path:
    """将 OrgTree 写回 positions.yaml。"""
    payload = deepcopy(meta)
    payload["positions"] = tree.to_list()
    return save_positions_data(project_dir, payload, reason=reason)
