from pathlib import Path
from unittest.mock import patch

import yaml

from agents.interactive import STUDIO_TASK_REL, build_interactive_argv, write_task_context_file
from core.terminal.agent_launcher import resolve_spawn_agent_id

_AGENTS_YAML = {
    "agents": {
        "hermes": {"command": "hermes", "byok": True},
        "opencode": {"command": "opencode", "byok": True},
        "claude-code": {"command": "claude", "byok": False},
    }
}


def _write_agents(root: Path) -> None:
    (root / "config" / "agents.yaml").write_text(
        yaml.dump(_AGENTS_YAML, allow_unicode=True),
        encoding="utf-8",
    )


@patch("core.config.agent_policy.agent_available", return_value=True)
def test_resolve_spawn_agent_id_uses_position_by_default(mock_avail, tmp_path: Path):
    root = tmp_path / "studio"
    (root / "config").mkdir(parents=True)
    _write_agents(root)
    (root / "config" / "platform.yaml").write_text(
        yaml.dump(
            {
                "agents": {"policy": "byok_only", "default": "opencode"},
                "orchestration": {"use_position_agent": True},
            }
        ),
        encoding="utf-8",
    )
    assert resolve_spawn_agent_id(root, "hermes") == "hermes"


@patch("core.config.agent_policy.agent_available", return_value=True)
def test_resolve_spawn_agent_id_override_byok_fallback(mock_avail, tmp_path: Path):
    root = tmp_path / "studio"
    (root / "config").mkdir(parents=True)
    _write_agents(root)
    (root / "config" / "platform.yaml").write_text(
        yaml.dump(
            {
                "agents": {"policy": "byok_only", "default": "opencode"},
                "orchestration": {
                    "use_position_agent": False,
                    "worker_terminal_agent": "claude-code",
                },
            }
        ),
        encoding="utf-8",
    )
    assert resolve_spawn_agent_id(root, "hermes") == "opencode"


def test_claude_interactive_argv_via_config(tmp_path: Path):
    worktree = tmp_path / "wt"
    worktree.mkdir()
    rel = write_task_context_file(worktree, "实现登录页")
    cfg = {
        "command": "claude",
        "flags_interactive": "",
        "interactive": {"mode": "append_system_prompt_file"},
    }
    argv = build_interactive_argv(cfg, task_file_rel=rel)
    assert argv[0].endswith("claude.exe") or argv[0] == "claude"
    assert "-p" not in argv
    assert "--append-system-prompt-file" in argv
