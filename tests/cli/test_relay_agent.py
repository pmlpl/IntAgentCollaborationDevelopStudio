# tests/cli/test_relay_agent.py
import json
from pathlib import Path

from cli.relay_agent import argv_needs_relay, wrap_argv_for_windows_terminal


def test_argv_needs_relay_detects_multiline():
    assert argv_needs_relay(["hermes", "-z", "a\nb", "chat"])
    assert not argv_needs_relay(["hermes", "chat", "--tui"])


def test_wrap_writes_json(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("cli.relay_agent.os.name", "nt")
    cwd = tmp_path / "proj"
    cwd.mkdir()
    long_argv = ["hermes", "-z", "line1\n{\"run_command\":\"python main.py\"}", "chat", "--tui"]
    wrapped = wrap_argv_for_windows_terminal(long_argv, cwd)
    assert wrapped[1:3] == ["-m", "cli.relay_agent"]
    json_path = Path(wrapped[3])
    assert json_path.is_file()
    assert json.loads(json_path.read_text(encoding="utf-8")) == long_argv
