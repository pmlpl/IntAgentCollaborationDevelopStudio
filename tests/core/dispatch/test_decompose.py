import json

from core.dispatch.decompose import (
    MARKER,
    apply_subtasks,
    generate_mock_subtasks,
    parse_manager_output,
)


def test_parse_manager_output():
    stdout = f"some text\n{MARKER}\n" + json.dumps([{"assignee": "a", "description": "d", "waits_on": []}])
    subs = parse_manager_output(stdout)
    assert subs[0]["assignee"] == "a"


def test_parse_manager_output_json_in_code_fence():
    body = json.dumps([{"assignee": "a", "description": "d", "waits_on": []}])
    stdout = f"分工说明\n```json\n{body}\n```"
    subs = parse_manager_output(stdout)
    assert subs[0]["assignee"] == "a"


def test_parse_manager_output_uses_last_marker():
    inner = json.dumps([{"assignee": "b", "description": "ok", "waits_on": []}])
    stdout = f"{MARKER}\n[invalid]\n说明\n{MARKER}\n{inner}"
    subs = parse_manager_output(stdout)
    assert subs[0]["assignee"] == "b"


def test_parse_manager_output_marker_only_fails():
    import pytest

    with pytest.raises(ValueError, match="no valid JSON"):
        parse_manager_output(f"说明\n{MARKER}\n")


def test_generate_mock_subtasks(tmp_path):
    import yaml

    project = tmp_path / "proj"
    project.mkdir()
    data = {
        "positions": [
            {"id": "mgr", "is_manager": True, "parent": None},
            {"id": "w1", "parent": "mgr", "title": "前端"},
        ]
    }
    (project / "positions.yaml").write_text(yaml.dump(data), encoding="utf-8")
    subs = generate_mock_subtasks(project, "做搜索")
    assert len(subs) == 1
    assert subs[0]["assignee"] == "w1"


def test_apply_subtasks_creates_files(tmp_path):
    import yaml

    project = tmp_path / "proj"
    (project / "tasks" / "active").mkdir(parents=True)
    (project / "agents" / "w1" / "inbox" / "processed").mkdir(parents=True)
    subs = [{"assignee": "w1", "description": "test", "waits_on": []}]
    apply_subtasks(project, "task-root", subs, "root desc", manager_id="mgr")
    assert (project / "tasks" / "active" / "task-root-w1.yaml").exists()
