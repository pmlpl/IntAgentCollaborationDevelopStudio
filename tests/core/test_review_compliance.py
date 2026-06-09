from core.dispatch.review_compliance import build_review_checklist, extract_required_skills
from core.org.tree_ops import OrgTree


def test_extract_required_skills():
    desc = "实现搜索 API，skills=fastapi-expert,python-async"
    assert extract_required_skills(desc) == ["fastapi-expert", "python-async"]


def test_build_review_checklist_includes_compliance(tmp_path):
    (tmp_path / "platform" / "skills").mkdir(parents=True)
    (tmp_path / "platform" / "skills" / "registry.yaml").write_text(
        "skills:\n  - id: fastapi-expert\n    name: FastAPI\n", encoding="utf-8"
    )
    positions = [
        {"id": "laowang", "parent": None, "is_manager": True, "resume": {}},
        {
            "id": "dazhuang",
            "resume": {"skills": ["fastapi-expert"]},
            "parent": "laowang",
        },
    ]
    tree = OrgTree(positions)
    task = {
        "description": "新增接口 skills=fastapi-expert",
        "assignee": "dazhuang",
    }
    lines = build_review_checklist(tmp_path, tree, task, positions[0])
    assert any("技能合规" in line for line in lines)
    assert any("fastapi-expert" in line for line in lines)
