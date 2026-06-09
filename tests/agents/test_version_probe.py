from pathlib import Path
from unittest.mock import patch

from agents.version_probe import (
    fetch_latest_version,
    npm_package_from_install,
    pip_package_from_install,
    probe_cli_version,
    version_is_newer,
)


def test_npm_package_from_install():
    assert npm_package_from_install("npm install -g @anthropic-ai/claude-code") == (
        "@anthropic-ai/claude-code"
    )
    assert npm_package_from_install("见文档") is None


def test_pip_package_from_install():
    assert pip_package_from_install("pip install aider-chat") == "aider-chat"
    assert pip_package_from_install("pip install -U hermes-agent") == "hermes-agent"


@patch("agents.version_probe.prepare_subprocess_argv")
@patch("agents.version_probe.resolve_agent_command")
@patch("agents.version_probe.subprocess.run")
def test_probe_cli_version(mock_run, mock_resolve, mock_prepare):
    mock_resolve.return_value = "/usr/bin/gemini"
    mock_prepare.return_value = ["/usr/bin/gemini", "--version"]
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = "gemini-cli version 1.2.3\n"
    mock_run.return_value.stderr = ""
    assert probe_cli_version("gemini") == "1.2.3"
    mock_prepare.assert_called_once_with(["gemini", "--version"], interactive=False)


def test_version_is_newer():
    assert version_is_newer("2.0.0", "1.9.9") is True
    assert version_is_newer("1.0.0", "1.0.0") is False
    assert version_is_newer("1.0.1", "1.0.0") is True


def test_fetch_latest_version_uses_cache(tmp_path: Path):
    cache_dir = tmp_path / ".studio" / "cache"
    cache_dir.mkdir(parents=True)
    cache_file = cache_dir / "agent-latest-versions.json"
    cache_file.write_text(
        '{"opencode": {"version": "0.9.0", "ts": 9999999999}}',
        encoding="utf-8",
    )
    with patch("agents.version_probe._fetch_npm_latest") as mock_npm:
        ver = fetch_latest_version(
            tmp_path,
            "opencode",
            npm_package="opencode-ai",
            allow_network=False,
        )
        mock_npm.assert_not_called()
    assert ver == "0.9.0"
