"""Tests for agents/chat_agent.py — AgentConfig and base_url support."""
from agents.chat_agent import AgentConfig


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
