from pathlib import Path

import yaml

from core.org.tree_ops import OrgTree
from core.platform.memory_client import MemoryError, search, upsert
from core.project import init_project


def _setup(tmp_path: Path) -> tuple[Path, Path, dict]:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "agents.yaml").write_text("agents: {}\n", encoding="utf-8")
    (tmp_path / "config" / "platform.yaml").write_text(
        "memory:\n  backend: file\n", encoding="utf-8"
    )
    init_project(tmp_path, "demo", project_path=tmp_path / "proj", description="t")
    project_dir = tmp_path / "proj" / ".studio"
    data = yaml.safe_load((project_dir / "positions.yaml").read_text(encoding="utf-8"))
    manager = next(p for p in data["positions"] if p["id"] == "laowang")
    return project_dir, manager, data


def test_memory_upsert_and_search(tmp_path: Path):
    project_dir, manager, data = _setup(tmp_path)
    upsert(
        tmp_path,
        project_dir,
        manager,
        "project/demo",
        "api-style",
        "REST API 使用 FastAPI 与 Pydantic 校验",
        project_id=data.get("project"),
    )
    hits = search(
        tmp_path,
        project_dir,
        manager,
        "project/demo",
        "FastAPI",
        project_id=data.get("project"),
    )
    assert len(hits) == 1
    assert hits[0]["key"] == "api-style"


def test_memory_agent_namespace_self_write(tmp_path: Path):
    project_dir, manager, data = _setup(tmp_path)
    upsert(
        tmp_path,
        project_dir,
        manager,
        "agent/laowang",
        "note",
        "主管私有笔记",
        project_id=data.get("project"),
    )
    hits = search(
        tmp_path,
        project_dir,
        manager,
        "agent/laowang",
        "笔记",
        project_id=data.get("project"),
    )
    assert hits


def test_memory_denied_cross_agent(tmp_path: Path):
    project_dir, _, data = _setup(tmp_path)
    xiaohong = next(p for p in data["positions"] if p["id"] == "xiaohong")
    try:
        search(
            tmp_path,
            project_dir,
            xiaohong,
            "agent/laowang",
            "笔记",
            project_id=data.get("project"),
        )
        assert False, "should deny"
    except MemoryError:
        pass
