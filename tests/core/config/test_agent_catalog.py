from pathlib import Path
from unittest.mock import patch

import yaml

from core.config.agent_catalog import AgentCatalogRow, build_agent_catalog, catalog_summary


def _write_catalog(root: Path) -> None:
    (root / "config").mkdir(parents=True)
    (root / "config" / "agents_catalog.yaml").write_text(
        yaml.dump(
            {
                "catalog": [
                    {
                        "id": "opencode",
                        "agent_id": "opencode",
                        "name": "OpenCode",
                        "command": "opencode",
                        "byok": True,
                        "install_cmd": "npm install -g opencode-ai",
                        "rank": 1,
                    },
                    {
                        "id": "copilot",
                        "agent_id": None,
                        "name": "Copilot",
                        "command": "copilot",
                        "byok": False,
                        "rank": 2,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    (root / "config" / "agents.yaml").write_text(
        yaml.dump({"agents": {"opencode": {"command": "opencode"}}}),
        encoding="utf-8",
    )


@patch("core.config.agent_catalog.fetch_latest_version")
@patch("core.config.agent_catalog.probe_cli_version_at")
@patch("core.config.agent_catalog.probe_cli_version")
@patch("core.config.agent_catalog.resolve_agent_command_cached")
def test_build_agent_catalog_installed_and_openable(
    mock_resolve, mock_probe, mock_probe_at, mock_latest, tmp_path: Path
):
    root = tmp_path / "studio"
    _write_catalog(root)

    def _resolve(cmd: str) -> str | None:
        return "C:\\fake\\opencode.exe" if cmd == "opencode" else None

    mock_resolve.side_effect = _resolve
    mock_probe.return_value = "1.0.0"
    mock_latest.return_value = "1.1.0"

    rows = build_agent_catalog(
        root, force=True, probe_versions=True, network_versions=True
    )
    assert len(rows) == 2
    opencode = next(r for r in rows if r.id == "opencode")
    copilot = next(r for r in rows if r.id == "copilot")
    assert opencode.installed is True
    assert opencode.launch_ready is True
    assert opencode.installed_version == "1.0.0"
    assert opencode.latest_version == "1.1.0"
    assert opencode.update_available is True
    assert copilot.installed is False
    assert copilot.openable is False

    stats = catalog_summary(rows)
    assert stats["installed"] == 1
    assert stats["openable_installed"] == 1


def test_fast_build_skips_version_probe(tmp_path: Path):
    root = tmp_path / "studio"
    _write_catalog(root)
    with patch("core.config.agent_catalog.probe_cli_version") as mock_probe:
        rows = build_agent_catalog(root, force=True, probe_versions=False)
        mock_probe.assert_not_called()
    assert len(rows) == 2


@patch("core.config.agent_catalog.resolve_agent_command_cached")
def test_install_probe_paths_when_not_in_path(mock_resolve, tmp_path: Path):
    """MSI 等固定目录安装：PATH 未进当前进程时仍应检测到。"""
    root = tmp_path / "studio"
    (root / "config").mkdir(parents=True)
    fake_exe = tmp_path / "Kiro-Cli" / "kiro-cli.exe"
    fake_exe.parent.mkdir(parents=True)
    fake_exe.write_bytes(b"")

    (root / "config" / "agents_catalog.yaml").write_text(
        yaml.dump(
            {
                "catalog": [
                    {
                        "id": "amazon-q-cli",
                        "agent_id": None,
                        "name": "Kiro",
                        "command": "kiro-cli",
                        "install_probe_paths": [str(fake_exe)],
                        "rank": 1,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (root / "config" / "agents.yaml").write_text(
        yaml.dump({"agents": {}}),
        encoding="utf-8",
    )
    mock_resolve.return_value = None

    rows = build_agent_catalog(root, force=True)
    row = rows[0]
    assert row.installed is True
    assert row.command_path == str(fake_exe)


def test_catalog_row_can_open_without_agent_id():
    row = AgentCatalogRow(
        id="copilot",
        agent_id=None,
        name="Copilot",
        tagline="",
        command="copilot",
        byok=False,
        installed=True,
        command_path="C:\\fake\\copilot.cmd",
        openable=False,
        launch_ready=False,
        launch_error="",
        install_cmd="npm install -g @github/copilot",
        apikey_hint="",
        rank=1,
    )
    with patch("core.config.agent_catalog.agent_launch_check_error", return_value=""):
        from core.config.agent_catalog import catalog_row_can_open

        assert catalog_row_can_open(row) is True
