from agents.registry import build_command


def test_build_command_claude_code():
    cfg = {"command": "claude", "flags": "-p"}
    cmd = build_command(cfg, task="hello", worktree="/tmp/wt")
    assert cmd[0] == "claude"
    assert "-p" in cmd
    assert "hello" in cmd
