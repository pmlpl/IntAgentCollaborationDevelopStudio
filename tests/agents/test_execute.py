import os
import shutil
import sys

import pytest

from agents.execute import agent_command_available, prepare_subprocess_argv


@pytest.mark.skipif(os.name != "nt", reason="Windows .cmd shim")
def test_prepare_subprocess_argv_resolves_claude_exe():
    """npm claude 应解析为 claude.exe 或可用的 powershell 调用。"""
    if not agent_command_available("claude"):
        pytest.skip("claude not on PATH")
    prompt = "你是技术主管。CEO 任务：hello"
    argv = prepare_subprocess_argv(["claude", "-p", prompt])
    head = argv[0].lower()
    if head.endswith("claude.exe"):
        assert argv[1:] == ["-p", prompt]
    elif head.endswith("powershell.exe"):
        joined = " ".join(argv).lower()
        assert "claude" in joined
    else:
        pytest.fail(f"unexpected launcher: {argv[0]}")
    assert not any(a.lower() == "cmd.exe" and "/c" in argv for a in argv)


def test_prepare_subprocess_argv_python():
    py = sys.executable
    argv = prepare_subprocess_argv([py, "-c", "print(1)"])
    assert argv[0] == py


@pytest.mark.skipif(os.name != "nt", reason="Windows .cmd shim")
def test_prepare_subprocess_argv_interactive_cmd_uses_k(tmp_path):
    """交互模式下 .cmd 应走 cmd /k，避免 /c 导致 TUI 退出后只剩空终端。"""
    shim = tmp_path / "fake.cmd"
    shim.write_text('@echo off\necho hello\n', encoding="utf-8")
    argv = prepare_subprocess_argv([str(shim)], interactive=True)
    assert argv[0].lower().endswith("cmd.exe")
    assert argv[1].lower() == "/k"
    assert argv[2] == str(shim)


@pytest.mark.skipif(os.name != "nt", reason="Windows node shim")
def test_prepare_subprocess_argv_resolves_node_shim(tmp_path):
    """npm .cmd 中的 node 脚本应解析为 node.exe + .js。"""
    base = tmp_path / "npm"
    base.mkdir()
    script = base / "node_modules" / "pkg" / "bin" / "cli.js"
    script.parent.mkdir(parents=True)
    script.write_text("console.log(1)", encoding="utf-8")
    shim = base / "tool.cmd"
    shim.write_text(f'@echo off\nnode "%dp0%\\node_modules\\pkg\\bin\\cli.js" %*\n', encoding="utf-8")
    if not shutil.which("node"):
        pytest.skip("node not on PATH")
    argv = prepare_subprocess_argv([str(shim), "chat", "--tui"], interactive=True)
    assert argv[0].lower().endswith("node.exe") or "node" in os.path.basename(argv[0]).lower()
    assert argv[1].endswith("cli.js")
    assert argv[2:] == ["chat", "--tui"]
