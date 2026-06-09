from core.terminal.install_launcher import is_runnable_install_cmd, spawn_install_terminal


def test_is_runnable_install_cmd():
    assert is_runnable_install_cmd("npm install -g opencode-ai")
    assert is_runnable_install_cmd("pip install aider-chat")
    assert not is_runnable_install_cmd("")
    assert is_runnable_install_cmd("goose configure")
    assert is_runnable_install_cmd(
        'powershell -NoProfile -ExecutionPolicy Bypass -Command "irm install.ps1 | iex"'
    )
    assert is_runnable_install_cmd("gh extension install github/gh-copilot")
