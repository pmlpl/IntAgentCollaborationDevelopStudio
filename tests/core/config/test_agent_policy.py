from pathlib import Path

from unittest.mock import patch

import yaml

from core.config.agent_policy import (
    agent_allowed,
    agent_auto_detect,
    agent_enabled,
    agent_is_byok,
    pick_spawn_agent_id,
    set_agent_enabled,
)


def test_agent_is_byok():
    assert agent_is_byok({"byok": True})
    assert not agent_is_byok({"byok": False})
    assert not agent_is_byok({})


def test_agent_enabled_when_not_in_disabled_list(tmp_path: Path):
    """Agent 不在 disabled 列表中时，auto_detect=false 时默认启用。"""
    root = tmp_path / "studio"
    (root / "config").mkdir(parents=True)
    (root / "config" / "agents.yaml").write_text(
        yaml.dump({"agents": {"opencode": {"byok": True, "command": "opencode"}}}),
        encoding="utf-8",
    )
    (root / "config" / "platform.yaml").write_text(
        yaml.dump({"agents": {"policy": "byok_only", "disabled": [], "auto_detect": False}}),
        encoding="utf-8",
    )
    assert agent_enabled(root, "opencode")


def test_agent_enabled_false_when_explicitly_disabled(tmp_path: Path):
    """显式加入 disabled 列表的 Agent 一定被禁用。"""
    root = tmp_path / "studio"
    (root / "config").mkdir(parents=True)
    (root / "config" / "agents.yaml").write_text(
        yaml.dump({"agents": {"claude-code": {"byok": False, "command": "claude"}}}),
        encoding="utf-8",
    )
    (root / "config" / "platform.yaml").write_text(
        yaml.dump({"agents": {"policy": "all", "disabled": ["claude-code"], "auto_detect": False}}),
        encoding="utf-8",
    )
    assert not agent_enabled(root, "claude-code")


def test_set_agent_enabled_writes_disabled_list(tmp_path: Path):
    """set_agent_enabled 应写入 disabled 列表。"""
    root = tmp_path / "studio"
    (root / "config").mkdir(parents=True)
    (root / "config" / "agents.yaml").write_text(
        yaml.dump({"agents": {"opencode": {"byok": True, "command": "opencode"}}}),
        encoding="utf-8",
    )
    (root / "config" / "platform.yaml").write_text(
        yaml.dump({"agents": {"policy": "byok_only", "disabled": [], "auto_detect": False}}),
        encoding="utf-8",
    )
    # 禁用
    set_agent_enabled(root, "opencode", False)
    assert not agent_enabled(root, "opencode")
    # 重新启用
    set_agent_enabled(root, "opencode", True)
    assert agent_enabled(root, "opencode")


def test_agent_allowed_respects_disabled(tmp_path: Path):
    """被禁用的 Agent 即使满足 byok 策略也不允许调度。"""
    root = tmp_path / "studio"
    (root / "config").mkdir(parents=True)
    (root / "config" / "agents.yaml").write_text(
        yaml.dump({"agents": {"opencode": {"byok": True, "command": "opencode"}}}),
        encoding="utf-8",
    )
    (root / "config" / "platform.yaml").write_text(
        yaml.dump({"agents": {"policy": "byok_only", "disabled": ["opencode"], "auto_detect": False}}),
        encoding="utf-8",
    )
    assert not agent_allowed(root, "opencode")


@patch("core.config.agent_policy.agent_available", return_value=False)
def test_agent_auto_detect_marks_uninstalled_disabled(mock_avail, tmp_path: Path):
    """auto_detect=true 时，未安装的 Agent 应检测为禁用。"""
    root = tmp_path / "studio"
    (root / "config").mkdir(parents=True)
    (root / "config" / "agents.yaml").write_text(
        yaml.dump({"agents": {"opencode": {"byok": True, "command": "opencode"}}}),
        encoding="utf-8",
    )
    (root / "config" / "platform.yaml").write_text(
        yaml.dump({"agents": {"policy": "byok_only", "disabled": [], "auto_detect": True}}),
        encoding="utf-8",
    )
    assert not agent_enabled(root, "opencode")
    detect = agent_auto_detect(root)
    assert detect == {"opencode": False}


def test_agent_allowed_byok_only(tmp_path: Path):
    root = tmp_path / "studio"
    (root / "config").mkdir(parents=True)
    (root / "config" / "agents.yaml").write_text(
        yaml.dump(
            {
                "agents": {
                    "opencode": {"byok": True, "command": "opencode"},
                    "claude-code": {"byok": False, "command": "claude"},
                }
            }
        ),
        encoding="utf-8",
    )
    (root / "config" / "platform.yaml").write_text(
        yaml.dump({"agents": {"policy": "byok_only", "disabled": [], "auto_detect": False}}),
        encoding="utf-8",
    )
    assert agent_allowed(root, "opencode")
    assert not agent_allowed(root, "claude-code")


@patch("core.config.agent_policy.agent_available", return_value=True)
def test_pick_spawn_agent_id_fallback(mock_avail, tmp_path: Path):
    root = tmp_path / "studio"
    (root / "config").mkdir(parents=True)
    (root / "config" / "agents.yaml").write_text(
        yaml.dump(
            {
                "agents": {
                    "claude-code": {"byok": False, "command": "claude"},
                    "opencode": {"byok": True, "command": "opencode"},
                }
            }
        ),
        encoding="utf-8",
    )
    (root / "config" / "platform.yaml").write_text(
        yaml.dump({"agents": {"policy": "byok_only", "disabled": [], "auto_detect": False, "default": "opencode"}}),
        encoding="utf-8",
    )
    assert pick_spawn_agent_id(root, "claude-code") == "opencode"
