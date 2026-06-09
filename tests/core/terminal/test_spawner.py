from pathlib import Path
from unittest.mock import patch

from core.terminal.spawner import build_spawn_command


def test_build_spawn_command_contains_agent_cmd():
    cmd = build_spawn_command(["echo", "hello"], Path("."), title="Test")
    joined = " ".join(cmd)
    assert "echo" in joined or "hello" in joined


@patch("core.terminal.spawner.find_terminal", return_value="wt")
def test_build_spawn_command_interactive_uses_cmd_k(_mock_term):
    cmd = build_spawn_command(
        ["claude"], Path("."), title="Worker", interactive=True
    )
    joined = " ".join(cmd)
    assert cmd[0] == "wt.exe"
    assert "--" in cmd
    assert "pause" not in joined


@patch("core.terminal.spawner.find_terminal", return_value="wt")
def test_build_spawn_command_interactive_wt_passes_argv_directly(_mock_term):
    argv = ["C:\\tools\\claude.exe", "--append-system-prompt-file", ".studio\\STUDIO_TASK.md"]
    cmd = build_spawn_command(argv, Path("C:\\proj"), title="Claude", interactive=True)
    assert cmd[0] == "wt.exe"
    sep = cmd.index("--")
    assert cmd[sep + 1 :] == argv
