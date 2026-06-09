from pathlib import Path

from core.project_profile import (
    ProjectProfile,
    load_profile,
    merge_research_into_profile,
    parse_profile_markdown,
    profile_context_for_prompt,
    render_profile_markdown,
    save_profile,
    update_profile_from_dict,
)
from core.research.agent_research import RESEARCH_MARKER, parse_research_output


def test_profile_roundtrip(tmp_path: Path):
    profile = ProjectProfile(
        description="贪吃蛇小游戏",
        domain="休闲游戏",
        org_template="minimal",
        technologies_primary=["JavaScript", "Canvas"],
        technologies_alternate=["Python", "Pygame"],
        research_summary="适合精小团队快速交付",
    )
    save_profile(tmp_path, profile)
    loaded = load_profile(tmp_path)
    assert loaded is not None
    assert loaded.description == "贪吃蛇小游戏"
    assert "JavaScript" in loaded.technologies_primary
    assert loaded.org_template == "minimal"


def test_merge_research_into_profile():
    base = ProjectProfile(description="OA", technologies_primary=["Vue3"])
    merged = merge_research_into_profile(
        base,
        description="OA 系统",
        technologies=["FastAPI"],
        domain="企业内部工具",
        summary="全栈 Web 方案",
        org_template="web-fullstack",
    )
    assert merged.technologies_primary == ["Vue3", "FastAPI"]
    assert merged.domain == "企业内部工具"


def test_profile_context_for_empty():
    assert "首次调研" in profile_context_for_prompt(None)


def test_parse_research_output_with_alternate():
    raw = (
        f"ok\n{RESEARCH_MARKER}\n"
        '{"technologies":["JS"],"technologies_alternate":["Pygame"],'
        '"domain":"游戏","similar_products":[],"similar_local_template":null,'
        '"recommended_template":"minimal","summary":"test"}'
    )
    data = parse_research_output(raw)
    assert data["technologies_alternate"] == ["Pygame"]
    assert data["domain"] == "游戏"


def test_update_profile_from_dict(tmp_path: Path):
    update_profile_from_dict(
        tmp_path,
        {
            "technologies": ["Vue3"],
            "technologies_alternate": ["React"],
            "domain": "Web",
            "recommended_template": "web-fullstack",
            "summary": "推荐全栈",
            "similar_products": [{"name": "demo", "note": "ref"}],
        },
        "博客系统",
    )
    p = load_profile(tmp_path)
    assert p is not None
    assert p.technologies_primary == ["Vue3"]
    assert p.similar_products[0]["name"] == "demo"
