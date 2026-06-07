# agents/claude_code.py — Claude Code subprocess 适配
from __future__ import annotations

import os
import subprocess

from agents.base import AgentRunContext, BaseAgentAdapter


class ClaudeCodeAdapter(BaseAgentAdapter):
    """Claude Code CLI 适配器。"""

    def __init__(self, command: str = "claude", flags: str = "-p"):
        self.command = command
        self.flags = flags.split()

    def build_command(self, ctx: AgentRunContext) -> list[str]:
        return [self.command, *self.flags, ctx.task]

    def run(self, ctx: AgentRunContext) -> int:
        cmd = self.build_command(ctx)
        env = os.environ.copy()
        env.update(ctx.env)
        result = subprocess.run(cmd, cwd=ctx.worktree, env=env)
        return result.returncode
