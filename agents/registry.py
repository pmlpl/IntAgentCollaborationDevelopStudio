# agents/registry.py — Agent 配置加载与命令构建
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agents.claude_code import ClaudeCodeAdapter
from agents.base import BaseAgentAdapter, AgentRunContext


def load_agents_config(root: Path) -> dict[str, Any]:
    path = root / "config" / "agents.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_agent_config(root: Path, agent_id: str) -> dict[str, Any]:
    agents = load_agents_config(root).get("agents", {})
    if agent_id not in agents:
        raise KeyError(f"unknown agent: {agent_id}")
    return agents[agent_id]


def build_command(cfg: dict[str, Any], task: str, worktree: str | Path) -> list[str]:
    adapter = get_adapter(cfg)
    ctx = AgentRunContext(task=task, worktree=Path(worktree))
    return adapter.build_command(ctx)


def get_adapter(cfg: dict[str, Any]) -> BaseAgentAdapter:
    command = cfg.get("command", "claude")
    flags = cfg.get("flags", "-p")
    if command == "claude":
        return ClaudeCodeAdapter(command=command, flags=flags)
    return ClaudeCodeAdapter(command=command, flags=flags)
