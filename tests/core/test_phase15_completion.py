from core.project import build_positions_data, customize_positions_data
from core.research.mock import mock_research


def test_customize_positions_remove_role():
    base = build_positions_data("demo", "test", "web-fullstack")
    data = customize_positions_data(base, disabled_role_ids={"xiaoyan"})
    ids = {p["id"] for p in data["positions"]}
    assert "xiaoyan" not in ids
    assert "laowang" in ids


def test_customize_positions_override_name():
    base = build_positions_data("demo", "test", "minimal")
    data = customize_positions_data(
        base,
        overrides={"xiaohong": {"name": "小红帽", "agent": "hermes"}},
    )
    xiaohong = next(p for p in data["positions"] if p["id"] == "xiaohong")
    assert xiaohong["name"] == "小红帽"
    assert xiaohong["agent"] == "hermes"
