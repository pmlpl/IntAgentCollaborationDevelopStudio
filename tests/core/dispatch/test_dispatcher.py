from pathlib import Path

import yaml

from core.dispatch.dispatcher import Dispatcher


def test_create_root_task(tmp_path: Path):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    positions = {
        "project": "test",
        "positions": [
            {
                "id": "laowang",
                "name": "老王",
                "parent": None,
                "is_manager": True,
                "agent": "claude-code",
                "model": "deepseek-v4-pro",
            },
        ],
    }
    (project_dir / "positions.yaml").write_text(
        yaml.dump(positions, allow_unicode=True), encoding="utf-8"
    )
    (project_dir / "tasks" / "active").mkdir(parents=True)
    (project_dir / "agents" / "laowang" / "inbox" / "processed").mkdir(parents=True)

    disp = Dispatcher(project_dir)
    task = disp.create_task("加个搜索框")
    assert task["status"] == "pending"
    inbox_files = list((project_dir / "agents" / "laowang" / "inbox").glob("*.json"))
    assert len(inbox_files) == 1
