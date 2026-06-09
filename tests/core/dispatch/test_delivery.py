# tests/core/dispatch/test_delivery.py
from pathlib import Path

import yaml

from core.dispatch.delivery import (
    apply_manager_verdict,
    infer_run_command,
    parse_manager_review_output,
    poll_worker_deliveries,
    process_worker_delivery,
    refresh_delivery_verification,
    resolve_worktree_from_deliver,
)


def _setup_project(tmp_path: Path) -> tuple[Path, Path]:
    """创建最小项目结构：project_root + .studio 数据目录。"""
    project_root = tmp_path / "demo"
    data_dir = project_root / ".studio"
    (data_dir / "tasks" / "active").mkdir(parents=True)
    (data_dir / "agents" / "laowang" / "inbox" / "processed").mkdir(parents=True)
    (data_dir / "shared").mkdir()
    positions = {
        "project": "demo",
        "positions": [{"id": "laowang", "name": "老王", "parent": None, "is_manager": True}],
    }
    (data_dir / "positions.yaml").write_text(
        yaml.dump(positions, allow_unicode=True), encoding="utf-8"
    )
    (data_dir / "shared" / "repo.yaml").write_text(
        yaml.dump({"repo_path": str(project_root.resolve())}), encoding="utf-8"
    )
    return project_root, data_dir


def test_infer_run_command_from_test_files(tmp_path: Path):
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / "test_app.py").write_text("def test_ok(): assert True", encoding="utf-8")
    cmd = infer_run_command(wt, {"files": ["test_app.py"]})
    assert "pytest" in cmd


def test_resolve_worktree_from_deliver(tmp_path: Path):
    project_root, data_dir = _setup_project(tmp_path)
    deliver = data_dir / "DELIVER.json"
    deliver.parent.mkdir(parents=True, exist_ok=True)
    deliver.write_text("{}", encoding="utf-8")
    wt = resolve_worktree_from_deliver(deliver, data_dir, project_root)
    assert wt == project_root.resolve()


def test_process_worker_delivery_moves_to_in_review(tmp_path: Path):
    project_root, data_dir = _setup_project(tmp_path)
    task_id = "task-abc-xiaohong"
    task = {
        "id": task_id,
        "assignee": "xiaohong",
        "status": "assigned",
        "description": "写测试",
    }
    (data_dir / "tasks" / "active" / f"{task_id}.yaml").write_text(
        yaml.dump(task, allow_unicode=True), encoding="utf-8"
    )
    (project_root / "ok.py").write_text("print('hi')", encoding="utf-8")
    deliver = {
        "task_id": task_id,
        "worker": "xiaohong",
        "summary": "完成",
        "files": ["ok.py"],
        "run_command": "python ok.py",
    }
    record = process_worker_delivery(
        data_dir, task, deliver, project_root, manager_id="laowang"
    )
    assert record["exit_code"] == 0
    updated = yaml.safe_load(
        (data_dir / "tasks" / "active" / f"{task_id}.yaml").read_text(encoding="utf-8")
    )
    assert updated["status"] == "in_review"


def test_poll_worker_deliveries(tmp_path: Path):
    project_root, data_dir = _setup_project(tmp_path)
    task_id = "task-poll-1"
    task = {"id": task_id, "assignee": "xiaohong", "status": "assigned"}
    (data_dir / "tasks" / "active" / f"{task_id}.yaml").write_text(
        yaml.dump(task, allow_unicode=True), encoding="utf-8"
    )
    (project_root / "main.py").write_text("print(1)", encoding="utf-8")
    deliver_path = data_dir / "DELIVER.json"
    import json

    deliver_path.write_text(
        json.dumps(
            {
                "task_id": task_id,
                "summary": "done",
                "files": ["main.py"],
                "run_command": "python main.py",
            }
        ),
        encoding="utf-8",
    )
    records = poll_worker_deliveries(data_dir, manager_id="laowang", project_root=project_root)
    assert len(records) == 1
    assert not deliver_path.exists()


def test_parse_manager_review_output():
    text = '结论 OK\n---STUDIO_REVIEW_JSON---\n{"verdict":"approved","comment":"通过"}'
    parsed = parse_manager_review_output(text)
    assert parsed["verdict"] == "approved"


def test_apply_manager_verdict_approved(tmp_path: Path):
    _, data_dir = _setup_project(tmp_path)
    task_id = "task-v1"
    task = {"id": task_id, "status": "in_review", "assignee": "xiaohong"}
    (data_dir / "tasks" / "active" / f"{task_id}.yaml").write_text(
        yaml.dump(task, allow_unicode=True), encoding="utf-8"
    )
    apply_manager_verdict(data_dir, task_id, "approved", manager_id="laowang")
    assert not (data_dir / "tasks" / "active" / f"{task_id}.yaml").exists()
    assert (data_dir / "tasks" / "archive" / f"{task_id}.yaml").is_file()


def test_refresh_delivery_verification(tmp_path: Path):
    project_root, data_dir = _setup_project(tmp_path)
    task_id = "task-refresh"
    (project_root / "test_x.py").write_text("def test_x(): assert 1", encoding="utf-8")
    from core.dispatch.delivery import save_delivery_record

    save_delivery_record(
        data_dir,
        task_id,
        {
            "task_id": task_id,
            "files": ["test_x.py"],
            "exit_code": -1,
            "run_command": "",
        },
    )
    refreshed = refresh_delivery_verification(data_dir, task_id, project_root=project_root)
    assert refreshed is not None
    assert refreshed["exit_code"] == 0
