# agents/base.py — Agent 适配器抽象基类
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AgentRunContext:
    """Agent 运行上下文。"""

    task: str
    worktree: Path
    skills: list[str] = field(default_factory=list)
    mcp_servers: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


class BaseAgentAdapter(ABC):
    """外部 CLI Agent 适配器基类。"""

    @abstractmethod
    def build_command(self, ctx: AgentRunContext) -> list[str]:
        ...

    @abstractmethod
    def run(self, ctx: AgentRunContext) -> int:
        ...
