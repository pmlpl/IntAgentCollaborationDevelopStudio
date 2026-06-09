# agents/claude_code.py — Claude Code subprocess 适配
from __future__ import annotations

import subprocess

from agents.base import AgentRunContext, BaseAgentAdapter
from agents.execute import agent_subprocess_env, prepare_subprocess_argv


class ClaudeCodeAdapter(BaseAgentAdapter):
    """Claude Code CLI 适配器。"""

    def __init__(self, command: str = "claude", flags: str = "-p", flags_interactive: str | None = None):
        self.command = command
        self.flags = flags.split()
        # 交互模式 flags；None 表示不带 -p，仅 command + 任务 prompt
        self.flags_interactive = (
            flags_interactive.split() if flags_interactive is not None else []
        )

    def build_command(self, ctx: AgentRunContext) -> list[str]:
        cmd = [self.command, *self.flags, ctx.task]
        # Claude Code 无 -s/--mcp 短参；skills/MCP 由 manifest + 项目配置加载，勿拼无效 CLI 参数
        _ = ctx.skills, ctx.mcp_servers
        return cmd

    def build_interactive_command(self, ctx: AgentRunContext) -> list[str]:
        """交互式 CLI：不加 -p、不把 task 作为 positional（非 TTY 会误走 print 模式）。"""
        cmd = [self.command, *self.flags_interactive]
        _ = ctx.task, ctx.skills, ctx.mcp_servers
        return cmd

    def run(self, ctx: AgentRunContext) -> int:
        cmd = prepare_subprocess_argv(self.build_command(ctx))
        env = agent_subprocess_env(ctx.env or None)
        result = subprocess.run(cmd, cwd=ctx.worktree, env=env)
        return result.returncode
