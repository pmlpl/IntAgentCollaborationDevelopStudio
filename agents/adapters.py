# agents/adapters.py — 各 Agent CLI 适配器（多态替换单一 ClaudeCodeAdapter）
from __future__ import annotations

import subprocess
from pathlib import Path

from agents.base import AgentRunContext, BaseAgentAdapter
from agents.execute import agent_subprocess_env, prepare_subprocess_argv


class ClaudeCodeAdapter(BaseAgentAdapter):
    """Claude Code CLI 适配器。"""

    def __init__(
        self,
        command: str = "claude",
        flags: str = "-p",
        flags_interactive: str | None = None,
    ):
        self.command = command
        self.flags = flags.split()
        self.flags_interactive = (
            flags_interactive.split() if flags_interactive is not None else []
        )

    def build_command(self, ctx: AgentRunContext) -> list[str]:
        return [
            self.command,
            *self.flags,
            "--dangerously-skip-permissions",
            ctx.task,
        ]

    def build_interactive_command(self, ctx: AgentRunContext) -> list[str]:
        return [self.command, *self.flags_interactive]

    def run(self, ctx: AgentRunContext) -> int:
        cmd = prepare_subprocess_argv(self.build_command(ctx))
        env = agent_subprocess_env(ctx.env or None)
        result = subprocess.run(cmd, cwd=ctx.worktree, env=env)
        return result.returncode


class OpenCodeAdapter(BaseAgentAdapter):
    """OpenCode CLI 适配器。

    headless capture:  opencode run --format json <task>
    交互式:            opencode run -i <task_text>
    """

    def __init__(
        self,
        command: str = "opencode",
        flags: str = "run",
        flags_interactive: str | None = None,
    ):
        self.command = command
        # headless 模式下用 run + --format json
        self.flags_headless = flags.split() if flags else ["run", "--format", "json"]
        self.flags_interactive = (
            flags_interactive.split() if flags_interactive is not None else []
        )

    def build_command(self, ctx: AgentRunContext) -> list[str]:
        """headless 模式：opencode run --format json --yes <task>"""
        cmd = [self.command, *self.flags_headless, "--yes", ctx.task]
        _ = ctx.skills, ctx.mcp_servers
        return cmd

    def build_interactive_command(self, ctx: AgentRunContext) -> list[str]:
        """交互式：opencode run -i <task_text>（由 launcher 调用时构建完整 argv）"""
        return [self.command, *self.flags_interactive]

    def run(self, ctx: AgentRunContext) -> int:
        cmd = prepare_subprocess_argv(self.build_command(ctx))
        env = agent_subprocess_env(ctx.env or None)
        result = subprocess.run(cmd, cwd=ctx.worktree, env=env)
        return result.returncode


class HermesAdapter(BaseAgentAdapter):
    """Hermes CLI 适配器。

    headless:  hermes chat -q <task>
    交互式:    hermes chat --tui（通过 .hermes.md + HERMES_TUI_QUERY 注入上下文）
    """

    def __init__(
        self,
        command: str = "hermes",
        flags: str = "chat -q",
        flags_interactive: str | None = "chat --tui",
    ):
        self.command = command
        self.flags = flags.split() if flags else ["chat", "-q"]
        self.flags_interactive = (
            flags_interactive.split()
            if flags_interactive is not None
            else ["chat", "--tui"]
        )

    def build_command(self, ctx: AgentRunContext) -> list[str]:
        return [self.command, *self.flags, "--yes", ctx.task]

    def build_interactive_command(self, ctx: AgentRunContext) -> list[str]:
        return [self.command, *self.flags_interactive]

    def run(self, ctx: AgentRunContext) -> int:
        cmd = prepare_subprocess_argv(self.build_command(ctx))
        env = agent_subprocess_env(ctx.env or None)
        result = subprocess.run(cmd, cwd=ctx.worktree, env=env)
        return result.returncode


class AiderAdapter(BaseAgentAdapter):
    """Aider CLI 适配器。

    headless:  aider --message <task> --yes --no-git  (--message 需要配合 --yes)
    交互式:    aider（由 launcher 构建 task_file_context）
    """

    def __init__(
        self,
        command: str = "aider",
        flags: str = "--message",
        flags_interactive: str | None = None,
    ):
        self.command = command
        # headless 模式追加 --yes 避免交互式确认
        self.flags_headless = (flags or "--message").split() + ["--yes"]
        self.flags_interactive = (
            flags_interactive.split() if flags_interactive is not None else []
        )

    def build_command(self, ctx: AgentRunContext) -> list[str]:
        return [self.command, *self.flags_headless, ctx.task]

    def build_interactive_command(self, ctx: AgentRunContext) -> list[str]:
        return [self.command, *self.flags_interactive]

    def run(self, ctx: AgentRunContext) -> int:
        cmd = prepare_subprocess_argv(self.build_command(ctx))
        env = agent_subprocess_env(ctx.env or None)
        result = subprocess.run(cmd, cwd=ctx.worktree, env=env)
        return result.returncode


class GooseAdapter(BaseAgentAdapter):
    """Goose CLI 适配器。

    headless:  goose run <task>
    交互式:    goose session（由 launcher 构建 task_file_context）
    """

    def __init__(
        self,
        command: str = "goose",
        flags: str = "run",
        flags_interactive: str | None = "session",
    ):
        self.command = command
        self.flags = flags.split() if flags else ["run"]
        self.flags_interactive = (
            flags_interactive.split()
            if flags_interactive is not None
            else ["session"]
        )

    def build_command(self, ctx: AgentRunContext) -> list[str]:
        return [self.command, *self.flags, "--yes", ctx.task]

    def build_interactive_command(self, ctx: AgentRunContext) -> list[str]:
        return [self.command, *self.flags_interactive]

    def run(self, ctx: AgentRunContext) -> int:
        cmd = prepare_subprocess_argv(self.build_command(ctx))
        env = agent_subprocess_env(ctx.env or None)
        result = subprocess.run(cmd, cwd=ctx.worktree, env=env)
        return result.returncode


class CodexAdapter(BaseAgentAdapter):
    """OpenAI Codex CLI 适配器。

    headless:  codex exec <task>
    交互式:    codex（由 launcher 构建 task_file_context）
    """

    def __init__(
        self,
        command: str = "codex",
        flags: str = "exec",
        flags_interactive: str | None = None,
    ):
        self.command = command
        self.flags = flags.split() if flags else ["exec"]
        self.flags_interactive = (
            flags_interactive.split() if flags_interactive is not None else []
        )

    def build_command(self, ctx: AgentRunContext) -> list[str]:
        return [self.command, *self.flags, ctx.task]

    def build_interactive_command(self, ctx: AgentRunContext) -> list[str]:
        return [self.command, *self.flags_interactive]

    def run(self, ctx: AgentRunContext) -> int:
        cmd = prepare_subprocess_argv(self.build_command(ctx))
        env = agent_subprocess_env(ctx.env or None)
        result = subprocess.run(cmd, cwd=ctx.worktree, env=env)
        return result.returncode


class GeminiCLIAdapter(BaseAgentAdapter):
    """Gemini CLI 适配器。

    headless:  gemini -p <task>
    交互式:    gemini（由 launcher 构建 task_file_context）
    """

    def __init__(
        self,
        command: str = "gemini",
        flags: str = "-p",
        flags_interactive: str | None = None,
    ):
        self.command = command
        self.flags = flags.split() if flags else ["-p"]
        self.flags_interactive = (
            flags_interactive.split() if flags_interactive is not None else []
        )

    def build_command(self, ctx: AgentRunContext) -> list[str]:
        return [self.command, *self.flags, ctx.task]

    def build_interactive_command(self, ctx: AgentRunContext) -> list[str]:
        return [self.command, *self.flags_interactive]

    def run(self, ctx: AgentRunContext) -> int:
        cmd = prepare_subprocess_argv(self.build_command(ctx))
        env = agent_subprocess_env(ctx.env or None)
        result = subprocess.run(cmd, cwd=ctx.worktree, env=env)
        return result.returncode


# ── 适配器注册表：command → Adapter 类 ──
# 每个 Agent 的 command（agents.yaml 中的 command 字段）映射到其适配器
_ADAPTER_REGISTRY: dict[str, type[BaseAgentAdapter]] = {
    "claude": ClaudeCodeAdapter,
    "opencode": OpenCodeAdapter,
    "hermes": HermesAdapter,
    "aider": AiderAdapter,
    "goose": GooseAdapter,
    "codex": CodexAdapter,
    "gemini": GeminiCLIAdapter,
}

# Agent ID → command 覆盖（当 agent_id 与 command 不同时）
_AGENT_ID_COMMAND_MAP: dict[str, str] = {
    "claude-code": "claude",
    "gemini-cli": "gemini",
}


def get_adapter_class(command: str) -> type[BaseAgentAdapter]:
    """根据 Agent CLI 的 command 字符串返回适配器类。未知 command 降级用 ClaudeCodeAdapter。"""
    return _ADAPTER_REGISTRY.get(command, ClaudeCodeAdapter)


def get_adapter_for_agent(agent_id: str, cfg: dict) -> BaseAgentAdapter:
    """根据 agent_id 和 agent 配置构建适配器实例。

    优先从 _AGENT_ID_COMMAND_MAP 解析 command，其次用 cfg.command。
    """
    command = _AGENT_ID_COMMAND_MAP.get(agent_id, cfg.get("command", agent_id))
    cls = get_adapter_class(command)
    flags = cfg.get("flags", "")
    flags_interactive = cfg.get("flags_interactive")
    return cls(command=command, flags=str(flags), flags_interactive=flags_interactive)
