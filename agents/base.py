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
    """外部 CLI Agent 适配器基类。

    子类只需实现 build_command()；build_interactive_command() 可选覆写。
    实际执行由 agents.runner / agents.registry 通过 subprocess 完成，
    适配器本身不负责 subprocess 调用。
    """

    @abstractmethod
    def build_command(self, ctx: AgentRunContext) -> list[str]:
        """构建 headless 捕获模式下的命令行参数。"""
        ...

    def build_interactive_command(self, ctx: AgentRunContext) -> list[str]:
        """构建交互式 TUI 模式下的命令行参数。默认等同于 headless 模式。"""
        return self.build_command(ctx)
