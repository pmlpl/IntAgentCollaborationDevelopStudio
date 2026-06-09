from pathlib import Path

import pytest
import yaml

from core.dispatch.decompose import MARKER, parse_manager_output, validate_subtasks
from core.research.templates import find_similar_template


def _minimal_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    positions = {
        "project": "demo",
        "positions": [
            {"id": "laowang", "name": "老王", "parent": None, "is_manager": True},
            {"id": "xiaohong", "name": "小红", "parent": "laowang"},
            {"id": "dazhuang", "name": "大壮", "parent": "laowang"},
        ],
    }
    (project / "positions.yaml").write_text(yaml.dump(positions), encoding="utf-8")
    return project


def test_parse_and_validate_subtasks(tmp_path: Path):
    project = _minimal_project(tmp_path)
    raw_stdout = (
        f"分析完成\n{MARKER}\n"
        '[{"assignee":"xiaohong","description":"前端实现","waits_on":[]},'
        '{"assignee":"dazhuang","description":"后端 API","waits_on":["xiaohong"]}]'
    )
    raw = parse_manager_output(raw_stdout)
    validated = validate_subtasks(raw, project, "laowang")
    assert validated[0]["assignee"] == "xiaohong"
    assert validated[1]["waits_on"] == ["xiaohong"]


def test_validate_rejects_manager_as_assignee(tmp_path: Path):
    project = _minimal_project(tmp_path)
    with pytest.raises(ValueError, match="invalid assignee"):
        validate_subtasks(
            [{"assignee": "laowang", "description": "自己干", "waits_on": []}],
            project,
            "laowang",
        )


def test_find_similar_template_vue_fastapi(tmp_path: Path):
    root = tmp_path / "studio"
    (root / "config" / "templates").mkdir(parents=True)
    src = (
        Path(__file__).resolve().parents[2]
        / "config"
        / "templates"
        / "web-fullstack-vue-fastapi.yaml"
    )
    (root / "config" / "templates" / "web-fullstack-vue-fastapi.yaml").write_text(
        src.read_text(encoding="utf-8"), encoding="utf-8"
    )
    similar = find_similar_template("Vue3 FastAPI 记账应用", root)
    assert similar is not None
    assert similar["org_template"] == "web-fullstack"
