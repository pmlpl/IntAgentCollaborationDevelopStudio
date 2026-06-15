"""Tests for cli/tui/widgets/model_config.py — ModelConfigBar config persistence."""
import tempfile
from pathlib import Path

from cli.tui.widgets.model_config import load_chat_settings, save_chat_settings


def test_load_settings_missing_file():
    """Loading from a non-existent file returns defaults."""
    with tempfile.TemporaryDirectory() as tmpdir:
        settings = load_chat_settings(Path(tmpdir))
        assert settings["model"] == "claude"
        assert settings["api_key"] == ""
        assert settings["base_url"] == ""


def test_save_and_load_roundtrip():
    """Saving and loading preserves all fields."""
    with tempfile.TemporaryDirectory() as tmpdir:
        save_chat_settings(Path(tmpdir), model="deepseek", api_key="sk-test123", base_url="https://x.com")
        settings = load_chat_settings(Path(tmpdir))
        assert settings["model"] == "deepseek"
        assert settings["api_key"] == "sk-test123"
        assert settings["base_url"] == "https://x.com"


def test_load_settings_partial_file():
    """Loading from a file with only some fields fills defaults for missing ones."""
    import yaml
    with tempfile.TemporaryDirectory() as tmpdir:
        config_dir = Path(tmpdir) / "config"
        config_dir.mkdir()
        (config_dir / "chat_settings.yaml").write_text(
            yaml.dump({"chat_model": {"model": "gpt", "api_key": "sk-partial"}}),
            encoding="utf-8",
        )
        settings = load_chat_settings(Path(tmpdir))
        assert settings["model"] == "gpt"
        assert settings["api_key"] == "sk-partial"
        assert settings["base_url"] == ""


def test_mask_api_key():
    """mask_key shows last 4 chars with asterisks."""
    from cli.tui.widgets.model_config import mask_key
    assert mask_key("") == "(未设置)"
    assert mask_key("sk-abc") == "**-abc"
    assert mask_key("sk-ant-12345678") == "***********5678"
    assert mask_key("short") == "*hort"  # 5 chars: first char masked, last 4 visible
