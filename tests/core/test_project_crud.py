from pathlib import Path

import pytest

from core.project import (
    DATA_DIR_NAME,
    build_positions_data,
    clear_stale_current_project,
    current_project_file,
    delete_project,
    get_registry_entry,
    init_project,
    list_org_templates,
    list_registered_projects,
    load_registry,
    project_exists,
    resolve_project_id,
    update_project,
    validate_new_project,
)


def test_build_positions_multi_endpoint():
    data = build_positions_data("demo", "全端项目", "multi-endpoint")
    ids = {p["id"] for p in data["positions"]}
    assert "xiaomo" in ids
    assert "xiaocheng" in ids
    assert "xiaozhuo" in ids
    assert len(ids) == 7


def test_org_templates_list():
    templates = list_org_templates()
    assert any(tid == "web-fullstack" for tid, _ in templates)


def test_project_update_and_delete(tmp_path: Path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "agents.yaml").write_text("agents: {}\n", encoding="utf-8")

    project_root = tmp_path / "myapp"
    init_project(tmp_path, "myapp", project_path=project_root, description="原始描述")

    updated = update_project(
        tmp_path,
        "myapp",
        name="我的应用",
        purpose="记账 App",
    )
    assert updated["name"] == "我的应用"
    assert updated["purpose"] == "记账 App"

    assert (project_root / DATA_DIR_NAME).exists()

    delete_project(tmp_path, "myapp", remove_folder=True)
    assert not project_root.exists()
    assert get_registry_entry(tmp_path, "myapp") is None

    init_project(tmp_path, "myapp2", project_path=tmp_path / "app2", description="x")
    delete_project(tmp_path, "myapp2", remove_folder=True)
    assert not (tmp_path / "app2").exists()
    assert load_registry(tmp_path)["projects"] == []


def test_validate_new_project_duplicate_name(tmp_path: Path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "agents.yaml").write_text("agents: {}\n", encoding="utf-8")

    project_root = tmp_path / "dup"
    init_project(tmp_path, "dup", project_path=project_root, description="重复测试")

    err = validate_new_project(tmp_path, "dup", project_root)
    assert err is not None
    assert "dup" in err
    assert "已在项目中心登记" in err


def test_validate_new_project_duplicate_path(tmp_path: Path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "agents.yaml").write_text("agents: {}\n", encoding="utf-8")

    project_root = tmp_path / "shared-path"
    init_project(tmp_path, "first", project_path=project_root, description="第一个")

    err = validate_new_project(tmp_path, "second", project_root)
    assert err is not None
    assert "路径已被项目" in err
    assert "first" in err


def test_init_project_rejects_duplicate(tmp_path: Path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "agents.yaml").write_text("agents: {}\n", encoding="utf-8")

    project_root = tmp_path / "again"
    init_project(tmp_path, "again", project_path=project_root, description="x")

    with pytest.raises(FileExistsError, match="已在项目中心登记"):
        init_project(tmp_path, "again", project_path=project_root, description="x")


def test_list_hides_deleted_project(tmp_path: Path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "agents.yaml").write_text("agents: {}\n", encoding="utf-8")
    project_root = tmp_path / "gone"
    init_project(tmp_path, "gone", project_path=project_root, description="x")
    delete_project(tmp_path, "gone", remove_folder=True)
    assert project_exists(tmp_path, "gone") is False
    assert list_registered_projects(tmp_path) == []


def test_resolve_clears_stale_current(tmp_path: Path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "agents.yaml").write_text("agents: {}\n", encoding="utf-8")
    (tmp_path / "projects").mkdir()
    current = current_project_file(tmp_path)
    current.parent.mkdir(parents=True, exist_ok=True)
    current.write_text("missing-project", encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        resolve_project_id(tmp_path)
    assert not current.exists()


def test_resolve_picks_remaining_after_delete(tmp_path: Path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "agents.yaml").write_text("agents: {}\n", encoding="utf-8")
    init_project(tmp_path, "keep", project_path=tmp_path / "keep", description="保留")
    init_project(tmp_path, "drop", project_path=tmp_path / "drop", description="删除")
    current = current_project_file(tmp_path)
    current.write_text("drop", encoding="utf-8")
    delete_project(tmp_path, "drop", remove_folder=True)
    assert resolve_project_id(tmp_path) == "keep"
