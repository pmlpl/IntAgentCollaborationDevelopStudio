from agents.registry import build_command


def test_build_command_claude_code():
    cfg = {"command": "claude", "flags": "-p"}
    cmd = build_command(cfg, task="hello", worktree="/tmp/wt")
    assert cmd[0] == "claude"
    assert "-p" in cmd
    assert "hello" in cmd
    assert "-s" not in cmd


def test_build_command_claude_code_skills_not_in_argv():
    """skills 写入 manifest，不注入 Claude 不支持的 -s 参数。"""
    cfg = {"command": "claude", "flags": "-p"}
    cmd = build_command(
        cfg,
        task="hello",
        worktree="/tmp/wt",
        skills=["vue-debug", "fastapi-expert"],
        mcp_servers=["codegraph"],
    )
    assert "-s" not in cmd
    assert "--mcp" not in cmd
    assert cmd == ["claude", "-p", "hello"]


def test_build_interactive_command_claude_no_print_flag():
    from agents.registry import build_interactive_command

    cfg = {"command": "claude", "flags": "-p", "flags_interactive": ""}
    cmd = build_interactive_command(cfg, task="做搜索框", worktree="/tmp/wt")
    assert cmd == ["claude"]
    assert "-p" not in cmd
