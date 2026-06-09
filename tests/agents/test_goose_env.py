from pathlib import Path

import yaml

from agents.goose_env import _config_has_provider, goose_provider_configured


def test_goose_provider_configured_false_when_no_provider(tmp_path, monkeypatch):
    cfg_dir = tmp_path / "Block" / "goose" / "config"
    cfg_dir.mkdir(parents=True)
    cfg_file = cfg_dir / "config.yaml"
    cfg_file.write_text("GOOSE_TELEMETRY_ENABLED: true\n", encoding="utf-8")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.delenv("GOOSE_PROVIDER", raising=False)
    assert not goose_provider_configured()


def test_goose_provider_configured_true_with_provider(tmp_path, monkeypatch):
    cfg_dir = tmp_path / "Block" / "goose" / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.yaml").write_text(
        yaml.dump({"GOOSE_PROVIDER": "openai", "GOOSE_MODEL": "gpt-4o"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert goose_provider_configured()


def test_goose_provider_configured_modern_active_provider(tmp_path, monkeypatch):
    """Goose 新版 config：active_provider + providers.*.configured"""
    cfg_dir = tmp_path / "Block" / "goose" / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.yaml").write_text(
        yaml.dump(
            {
                "active_provider": "custom_lmstudio",
                "providers": {
                    "custom_lmstudio": {
                        "enabled": True,
                        "model": "qwen3.5-9b",
                        "configured": True,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert goose_provider_configured()


def test_config_has_provider():
    assert _config_has_provider({"GOOSE_PROVIDER": "ollama"})
    assert not _config_has_provider({"GOOSE_TELEMETRY_ENABLED": True})
