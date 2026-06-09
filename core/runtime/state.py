# core/runtime/state.py — Agent 运行时状态 persistence
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class AgentRuntimeState:
    """单个岗位的 runtime 状态。"""

    task_id: str | None = None
    status: str = "idle"  # idle | working | submitted | blocked
    progress: int = 0
    message: str = ""


def _state_path(agent_dir: Path) -> Path:
    return agent_dir / "runtime" / "state.json"


def write_state(agent_dir: Path, state: AgentRuntimeState) -> None:
    path = _state_path(agent_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(state), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def read_state(agent_dir: Path) -> AgentRuntimeState:
    path = _state_path(agent_dir)
    if not path.exists():
        return AgentRuntimeState()
    data = json.loads(path.read_text(encoding="utf-8"))
    return AgentRuntimeState(**data)
