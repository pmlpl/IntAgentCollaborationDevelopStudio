# agents/registry.py — Agent 配置加载与命令构建
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agents.claude_code import ClaudeCodeAdapter
from agents.base import BaseAgentAdapter, AgentRunContext

# agents.yaml 按 mtime 缓存，避免每次 spawn / 列表重复 parse
_agents_yaml_cache: tuple[float, dict[str, Any]] | None = None


def load_agents_config(root: Path) -> dict[str, Any]:
    path = root / "config" / "agents.yaml"
    mtime = path.stat().st_mtime
    global _agents_yaml_cache
    if _agents_yaml_cache and _agents_yaml_cache[0] == mtime:
        return _agents_yaml_cache[1]
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    _agents_yaml_cache = (mtime, data)
    return data


def invalidate_agents_config_cache() -> None:
    """配置变更后清缓存。"""
    global _agents_yaml_cache
    _agents_yaml_cache = None


def load_agent_config(root: Path, agent_id: str) -> dict[str, Any]:
    agents = load_agents_config(root).get("agents", {})
    if agent_id not in agents:
        raise KeyError(f"unknown agent: {agent_id}")
    return agents[agent_id]


def build_command(
    cfg: dict[str, Any],
    task: str,
    worktree: str | Path,
    *,
    skills: list[str] | None = None,
    mcp_servers: list[str] | None = None,
) -> list[str]:
    adapter = get_adapter(cfg)
    ctx = AgentRunContext(
        task=task,
        worktree=Path(worktree),
        skills=skills or [],
        mcp_servers=mcp_servers or [],
    )
    return adapter.build_command(ctx)


def get_adapter(cfg: dict[str, Any]) -> BaseAgentAdapter:
    command = cfg.get("command", "claude")
    flags = cfg.get("flags", "-p")
    flags_interactive = cfg.get("flags_interactive")
    if command == "claude":
        return ClaudeCodeAdapter(
            command=command, flags=flags, flags_interactive=flags_interactive
        )
    return ClaudeCodeAdapter(
        command=command, flags=flags, flags_interactive=flags_interactive
    )


def build_interactive_command(
    cfg: dict[str, Any],
    task: str,
    worktree: str | Path,
    *,
    skills: list[str] | None = None,
    mcp_servers: list[str] | None = None,
) -> list[str]:
    """构建交互式 Agent 命令（Worker 终端用）。"""
    adapter = get_adapter(cfg)
    ctx = AgentRunContext(
        task=task,
        worktree=Path(worktree),
        skills=skills or [],
        mcp_servers=mcp_servers or [],
    )
    if hasattr(adapter, "build_interactive_command"):
        return adapter.build_interactive_command(ctx)
    return adapter.build_command(ctx)
