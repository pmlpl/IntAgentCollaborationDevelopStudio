"""Tests for agents/chat_agent.py — AgentConfig, base_url, and system prompt."""
import tempfile
from pathlib import Path

import yaml

from agents.chat_agent import AgentConfig, build_chat_system_prompt, check_connection


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


def test_build_chat_system_prompt_no_project():
    """Without project_dir, returns base prompt only."""
    prompt = build_chat_system_prompt(None)
    assert "主管" in prompt
    assert "团队" not in prompt or "Worker Agent" in prompt


def test_build_chat_system_prompt_with_positions():
    """With a project_dir containing positions.yaml, injects team info."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        positions_data = {
            "project": "测试项目",
            "description": "一个测试项目",
            "positions": [
                {
                    "id": "laowang", "name": "老王", "title": "技术主管",
                    "parent": None, "is_manager": True, "agent": "opencode",
                    "model": "deepseek-v4-pro",
                    "resume": {"strengths": ["任务拆解"]},
                },
                {
                    "id": "xiaohong", "name": "小红", "title": "前端开发",
                    "parent": "laowang", "agent": "opencode",
                    "model": "deepseek-v4-flash",
                    "resume": {"strengths": ["Vue3组件", "Pinia"]},
                },
                {
                    "id": "dazhuang", "name": "大壮", "title": "后端开发",
                    "parent": "laowang", "agent": "hermes",
                    "model": "deepseek-v4-pro",
                    "resume": {"strengths": ["REST API"]},
                },
            ],
        }
        (project_dir / "positions.yaml").write_text(
            yaml.dump(positions_data, allow_unicode=True),
            encoding="utf-8",
        )

        prompt = build_chat_system_prompt(project_dir)
        # 应包含项目信息
        assert "测试项目" in prompt
        # 应包含团队成员
        assert "小红" in prompt
        assert "大壮" in prompt
        # 应包含擅长领域
        assert "Vue3组件" in prompt
        assert "REST API" in prompt
        # 不应包含 manager 自己（老王）
        assert "老王" not in prompt
        # 应包含 agent 信息
        assert "agent=hermes" in prompt
