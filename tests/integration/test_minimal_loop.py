from pathlib import Path

import yaml

from cli.studio import main
from core.dispatch.dispatcher import Dispatcher
from core.project import (
    DATA_DIR_NAME,
    get_registry_entry,
    init_project,
    list_registered_projects,
    load_project,
    registry_path,
)


def test_studio_init_creates_project(tmp_path: Path, monkeypatch):
    # 在临时目录模拟 studio 根
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "agents.yaml").write_text("agents: {}\n", encoding="utf-8")
    (tmp_path / "config" / "models.yaml").write_text("models: {}\n", encoding="utf-8")
    (tmp_path / "config" / "platform.yaml").write_text(
        "supervisor:\n  port_range: [41000, 41010]\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    project_root = tmp_path / "demo"
    rc = main(["init", "--name", "demo", "--path", str(project_root)])
    assert rc == 0

    data_dir = project_root / DATA_DIR_NAME
    assert (data_dir / "positions.yaml").exists()
    assert (data_dir / "agents" / "laowang" / "inbox").is_dir()
    assert registry_path(tmp_path).exists()
    entry = get_registry_entry(tmp_path, "demo")
    assert entry is not None
    assert entry["path"] == str(project_root.resolve())


def test_integration_minimal_loop(tmp_path: Path, monkeypatch):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "agents.yaml").write_text("agents: {}\n", encoding="utf-8")
    (tmp_path / "config" / "models.yaml").write_text("models: {}\n", encoding="utf-8")
    (tmp_path / "config" / "platform.yaml").write_text(
        "supervisor:\n  port_range: [41000, 41010]\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    project_root = tmp_path / "demo"
    main(["init", "--name", "demo", "--path", str(project_root)])
    main(["task", "创建 README"])
    rc = main(["status"])
    assert rc == 0

    data_dir = load_project(tmp_path, "demo")
    tasks = list((data_dir / "tasks" / "active").glob("*.yaml"))
    assert len(tasks) == 1
    task = yaml.safe_load(tasks[0].read_text(encoding="utf-8"))
    assert task["status"] == "pending"

    disp = Dispatcher(data_dir)
    inbox_files = list((data_dir / "agents" / "laowang" / "inbox").glob("*.json"))
    assert len(inbox_files) == 1

    rc = main(["review"])
    assert rc == 0


def test_list_registered_projects(tmp_path: Path):
    (tmp_path / "projects").mkdir()
    project_root = tmp_path / "projects" / "alpha"
    init_project(tmp_path, "alpha", project_path=project_root, description="Alpha 项目")

    items = list_registered_projects(tmp_path)
    assert len(items) == 1
    assert items[0]["id"] == "alpha"
    assert "Alpha" in items[0]["purpose"]
