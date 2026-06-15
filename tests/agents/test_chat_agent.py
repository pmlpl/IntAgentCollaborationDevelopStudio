"""Tests for agents/chat_agent.py — AgentConfig and base_url support."""
from agents.chat_agent import AgentConfig, check_connection


def test_agent_config_default_base_url():
    """AgentConfig should default base_url to empty string."""
    cfg = AgentConfig()
    assert cfg.base_url == ""


def test_agent_config_custom_base_url():
    """AgentConfig should accept a custom base_url."""
    cfg = AgentConfig(base_url="https://my-proxy.example.com/v1")
    assert cfg.base_url == "https://my-proxy.example.com/v1"


def test_agent_config_fields_preserved():
    """Adding base_url should not break existing fields."""
    cfg = AgentConfig(model="deepseek", api_key="sk-test", base_url="https://x.com")
    assert cfg.model == "deepseek"
    assert cfg.api_key == "sk-test"
    assert cfg.max_tokens == 4096
    assert cfg.temperature == 0.7


def test_check_connection_no_key():
    """check_connection fails gracefully when no API key is set."""
    cfg = AgentConfig(model="claude")
    # 确保环境变量不干扰
    import os
    old_key = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        ok, msg = check_connection(cfg)
        assert ok is False
        assert "API Key" in msg or "未设置" in msg
    finally:
        if old_key is not None:
            os.environ["ANTHROPIC_API_KEY"] = old_key
