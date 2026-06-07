from pathlib import Path

import yaml

from cli.studio import main
from core.dispatch.dispatcher import Dispatcher
from core.project import init_project, get_studio_root, set_current_project


def test_studio_init_creates_project(tmp_path: Path, monkeypatch):
    # 在临时目录模拟 studio 根
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "agents.yaml").write_text("agents: {}\n", encoding="utf-8")
    (tmp_path / "config" / "models.yaml").write_text("models: {}\n", encoding="utf-8")
    (tmp_path / "config" / "platform.yaml").write_text(
        "supervisor:\n  port_range: [41000, 41010]\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    rc = main(["init", "--name", "demo", "--repo", str(tmp_path)])
    assert rc == 0
    project_dir = tmp_path / "projects" / "demo"
    assert (project_dir / "positions.yaml").exists()
    assert (project_dir / "agents" / "laowang" / "inbox").is_dir()


def test_integration_minimal_loop(tmp_path: Path, monkeypatch):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "agents.yaml").write_text("agents: {}\n", encoding="utf-8")
    (tmp_path / "config" / "models.yaml").write_text("models: {}\n", encoding="utf-8")
    (tmp_path / "config" / "platform.yaml").write_text(
        "supervisor:\n  port_range: [41000, 41010]\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    main(["init", "--name", "demo", "--repo", str(tmp_path)])
    main(["task", "创建 README"])
    rc = main(["status"])
    assert rc == 0

    project_dir = tmp_path / "projects" / "demo"
    tasks = list((project_dir / "tasks" / "active").glob("*.yaml"))
    assert len(tasks) == 1
    task = yaml.safe_load(tasks[0].read_text(encoding="utf-8"))
    assert task["status"] == "pending"

    disp = Dispatcher(project_dir)
    inbox_files = list((project_dir / "agents" / "laowang" / "inbox").glob("*.json"))
    assert len(inbox_files) == 1

    rc = main(["review"])
    assert rc == 0
