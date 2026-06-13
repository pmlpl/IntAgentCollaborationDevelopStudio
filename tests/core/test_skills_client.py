from pathlib import Path

import yaml

from agents.registry import build_command
from agents.runner import run_position_task
from core.platform.skills_client import (
    prepare_worker_runtime,
    resolve_skills_for_position,
)
from core.project import init_project


def test_resolve_skills_for_position(tmp_path: Path):
    (tmp_path / "platform" / "skills" / "packages" / "fastapi-expert").mkdir(parents=True)
    (tmp_path / "platform" / "skills" / "registry.yaml").write_text(
        "skills:\n  - id: fastapi-expert\n    name: FastAPI\n    package: packages/fastapi-expert\n",
        encoding="utf-8",
    )
    position = {
        "id": "dazhuang",
        "resume": {"skills": ["fastapi-expert", "unknown-skill"]},
    }
    resolved = resolve_skills_for_position(tmp_path, position)
    assert resolved == ["fastapi-expert"]


def test_prepare_worker_runtime_writes_manifest(tmp_path: Path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "agents.yaml").write_text(
        "agents:\n  hermes:\n    command: echo\n    flags: ''\n", encoding="utf-8"
    )
    registry = tmp_path / "platform" / "skills"
    (registry / "packages" / "fastapi-expert").mkdir(parents=True)
    (registry / "registry.yaml").write_text(
        "skills:\n  - id: fastapi-expert\n    name: FastAPI\n    package: packages/fastapi-expert\n",
        encoding="utf-8",
    )
    init_project(tmp_path, "demo", project_path=tmp_path / "proj", description="t")
    project_dir = tmp_path / "proj" / ".studio"
    data = yaml.safe_load((project_dir / "positions.yaml").read_text(encoding="utf-8"))
    dazhuang = next(p for p in data["positions"] if p["id"] == "dazhuang")
    skills, mcp = prepare_worker_runtime(tmp_path, project_dir, "dazhuang", dazhuang)
    assert "fastapi-expert" in skills
    manifest = project_dir / "agents" / "dazhuang" / "runtime" / "skills.manifest.yaml"
    assert manifest.exists()


def test_build_command_skills_not_in_argv():
    """skills 写入 manifest，不注入 Hermes 不支持的 CLI 参数。"""
    cfg = {"command": "hermes", "flags": "chat -q"}
    cmd = build_command(
        cfg,
        task="do work",
        worktree=".",
        skills=["fastapi-expert", "python-async"],
    )
    assert cmd == ["hermes", "chat", "-q", "--yes", "do work"]
    assert "-s" not in cmd


def test_run_position_task_mock_writes_manifest(tmp_path: Path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "agents.yaml").write_text(
        "agents:\n  hermes:\n    command: nonexistent-cmd-xyz\n    flags: ''\n",
        encoding="utf-8",
    )
    (tmp_path / "platform" / "skills" / "packages" / "vue-debug").mkdir(parents=True)
    (tmp_path / "platform" / "skills" / "registry.yaml").write_text(
        "skills:\n  - id: vue-debug\n    name: Vue\n    package: packages/vue-debug\n",
        encoding="utf-8",
    )
    init_project(tmp_path, "demo", project_path=tmp_path / "proj", description="t")
    project_dir = tmp_path / "proj" / ".studio"
    run_position_task(
        tmp_path, project_dir, "xiaohong", "test task", mock=True
    )
    manifest = project_dir / "agents" / "xiaohong" / "runtime" / "skills.manifest.yaml"
    assert manifest.exists()
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    assert any(s["id"] == "vue-debug" for s in data["skills"])
