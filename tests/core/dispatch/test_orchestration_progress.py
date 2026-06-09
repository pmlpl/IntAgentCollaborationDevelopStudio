from pathlib import Path

import yaml

from core.dispatch.dispatcher import Dispatcher
from core.dispatch.orchestration_progress import compute_orchestration_progress
from core.runtime.state import AgentRuntimeState, write_state


def _setup_project(tmp_path: Path) -> Dispatcher:
    project = tmp_path / "proj"
    project.mkdir()
    positions = {
        "project": "demo",
        "positions": [
            {"id": "laowang", "name": "老王", "parent": None, "is_manager": True},
            {"id": "xiaohong", "name": "小红", "parent": "laowang"},
        ],
    }
    (project / "positions.yaml").write_text(yaml.dump(positions), encoding="utf-8")
    (project / "tasks" / "active").mkdir(parents=True)
    (project / "agents" / "laowang" / "runtime").mkdir(parents=True)
    return Dispatcher(project)


def test_orchestration_progress_after_create(tmp_path: Path):
    disp = _setup_project(tmp_path)
    task = disp.create_task("加搜索框")
    prog = compute_orchestration_progress(disp.project_dir, task["id"], description="加搜索框")
    assert prog.percent == 25
    assert prog.steps[0].done
    assert prog.steps[1].active is False


def test_orchestration_progress_manager_working(tmp_path: Path):
    disp = _setup_project(tmp_path)
    task = disp.create_task("加搜索框")
    write_state(
        disp.project_dir / "agents" / "laowang",
        AgentRuntimeState(
            task_id=task["id"],
            status="working",
            progress=50,
            message="正在拆解任务…",
        ),
    )
    prog = compute_orchestration_progress(disp.project_dir, task["id"])
    assert 25 <= prog.percent < 50
    assert prog.steps[1].active
    assert "拆解" in prog.message


def test_orchestration_progress_decomposed(tmp_path: Path):
    import json

    disp = _setup_project(tmp_path)
    task = disp.create_task("加搜索框")
    runtime = disp.project_dir / "agents" / "laowang" / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / "decompose_result.json").write_text(
        json.dumps([{"assignee": "xiaohong", "description": "前端", "waits_on": []}]),
        encoding="utf-8",
    )
    prog = compute_orchestration_progress(disp.project_dir, task["id"])
    assert prog.percent >= 50
    assert prog.steps[1].done
