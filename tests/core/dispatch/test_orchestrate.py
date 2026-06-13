from pathlib import Path

import yaml

from core.dispatch.dispatcher import Dispatcher


def test_begin_and_complete_orchestration(tmp_path: Path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "agents.yaml").write_text("agents: {}\n", encoding="utf-8")
    (tmp_path / "config" / "platform.yaml").write_text(
        "agents:\n  policy: all\n", encoding="utf-8"
    )
    project = tmp_path / "proj"
    project.mkdir()
    positions = {
        "project": "demo",
        "positions": [
            {"id": "laowang", "name": "老王", "parent": None, "is_manager": True, "agent": "claude-code"},
            {"id": "xiaohong", "name": "小红", "parent": "laowang", "agent": "claude-code"},
        ],
    }
    (project / "positions.yaml").write_text(yaml.dump(positions), encoding="utf-8")
    (project / "tasks" / "active").mkdir(parents=True)
    (project / "agents" / "laowang" / "inbox" / "processed").mkdir(parents=True)
    (project / "agents" / "xiaohong" / "inbox" / "processed").mkdir(parents=True)
    (project / "shared").mkdir()

    disp = Dispatcher(project)
    task = disp.begin_orchestration(tmp_path, "加搜索框", spawn_terminals=False, mock=True)
    assert disp.try_complete_orchestration(tmp_path, task["id"], spawn_terminals=False)
    assert disp.try_complete_orchestration(tmp_path, task["id"], spawn_terminals=False)
    marker = project / "tasks" / "active" / f".orchestrated-{task['id']}.json"
    assert marker.exists()
    tasks = disp.get_status()
    assert any(t.get("parent_id") == task["id"] for t in tasks)
