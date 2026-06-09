# core/dispatch/orchestration_progress.py — 任务编排进度（按真实步骤计算，非假进度）
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.dispatch.decompose import load_decompose_result
from core.runtime.state import AgentRuntimeState, read_state

STEP_COUNT = 5
STEP_WEIGHT = 100 // STEP_COUNT  # 每完成一步 20%


@dataclass
class OrchestrationStep:
    """编排流水线中的单步。"""

    label: str
    done: bool
    active: bool = False
    detail: str = ""


@dataclass
class OrchestrationProgress:
    """当前根任务的编排进度。"""

    task_id: str
    description: str
    percent: int
    message: str
    steps: list[OrchestrationStep] = field(default_factory=list)
    done: bool = False
    failed: bool = False


def _root_manager_id(project_dir: Path) -> str:
    import yaml

    from core.org.tree_ops import OrgTree

    data = yaml.safe_load((project_dir / "positions.yaml").read_text(encoding="utf-8"))
    tree = OrgTree.from_yaml_data(data)
    managers = tree.root_managers()
    if not managers:
        return "laowang"
    return managers[0]


def _load_spawned_worker_ids(project_dir: Path, root_task_id: str) -> set[str]:
    """读取已 spawn 的 Worker 子任务 id 集合。"""
    path = project_dir / "tasks" / "active" / f".workers-{root_task_id}.json"
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return set(data if isinstance(data, list) else [])
    except json.JSONDecodeError:
        return set()


def _manager_on_root_task(state: AgentRuntimeState, root_task_id: str) -> bool:
    """主管 runtime 是否绑定当前根任务。"""
    if not state.task_id:
        return True
    return state.task_id == root_task_id


def compute_orchestration_progress(
    project_dir: Path,
    root_task_id: str,
    *,
    description: str = "",
    tasks: list[dict[str, Any]] | None = None,
    states: dict[str, AgentRuntimeState] | None = None,
) -> OrchestrationProgress:
    """根据任务文件、decompose 结果、spawn 记录计算真实进度。"""
    manager_id = _root_manager_id(project_dir)
    manager_dir = project_dir / "agents" / manager_id
    manager_state = (
        states.get(manager_id) if states else read_state(manager_dir)
    )
    if manager_state is None:
        manager_state = read_state(manager_dir)

    active_dir = project_dir / "tasks" / "active"
    if tasks is None:
        import yaml

        tasks = []
        if active_dir.exists():
            for path in sorted(active_dir.glob("*.yaml")):
                tasks.append(yaml.safe_load(path.read_text(encoding="utf-8")))

    root_task = next((t for t in tasks if t.get("id") == root_task_id), None)
    if not description and root_task:
        description = str(root_task.get("description", ""))

    decompose = load_decompose_result(project_dir, manager_id)
    children = [t for t in tasks if t.get("parent_id") == root_task_id]
    assigned_children = [t for t in children if t.get("status") == "assigned"]
    spawned_ids = _load_spawned_worker_ids(project_dir, root_task_id)
    assigned_ids = {str(t.get("id") or "") for t in assigned_children}
    spawned_for_assigned = assigned_ids & spawned_ids

    on_task = _manager_on_root_task(manager_state, root_task_id)

    step_created = root_task is not None
    step_manager_running = step_created and on_task and (
        manager_state.status == "working"
        or (manager_state.status == "submitted" and decompose is None)
    )
    step_decomposed = decompose is not None
    step_assigned = len(children) > 0
    step_workers = (
        step_assigned
        and len(assigned_children) > 0
        and len(spawned_for_assigned) >= len(assigned_ids)
    )
    if step_assigned and not assigned_children:
        # 全部子任务处于 blocked 等状态，也算下发完成
        step_workers = step_assigned

    manager_msg = (manager_state.message or "").strip()
    failed = (
        on_task
        and manager_state.status == "idle"
        and (
            manager_msg.startswith("拆解解析失败")
            or "执行失败" in manager_msg
            or manager_msg.startswith("Agent 启动失败")
        )
    )

    steps = [
        OrchestrationStep(
            "1. 创建根任务",
            step_created,
            active=step_created and not step_decomposed and not step_manager_running and not failed,
            detail=root_task_id if step_created else "",
        ),
        OrchestrationStep(
            "2. 主管拆解中",
            step_decomposed,
            active=step_manager_running and not failed,
            detail=manager_msg if step_manager_running else "",
        ),
        OrchestrationStep(
            "3. 子任务已写入",
            step_assigned,
            active=step_decomposed and not step_assigned and not failed,
            detail=f"{len(children)} 个" if step_assigned else "",
        ),
        OrchestrationStep(
            "4. 启动 Worker 终端",
            step_workers,
            active=step_assigned and not step_workers and bool(assigned_children) and not failed,
            detail=f"{len(spawned_for_assigned)}/{len(assigned_ids)} 已打开"
            if assigned_children
            else ("依赖未满足，暂无需开工" if step_assigned else ""),
        ),
    ]

    done = step_workers and step_decomposed and step_assigned and step_created and not failed
    percent = 0
    if step_created:
        percent = 25
    if step_decomposed:
        percent = 50
    elif step_manager_running and not failed:
        percent = 25 + int(min(24, manager_state.progress * 25 / 100))
    if step_assigned:
        percent = max(percent, 75)
    if step_workers:
        percent = 100
    elif step_assigned and assigned_children and not failed:
        ratio = len(spawned_for_assigned) / max(1, len(assigned_ids))
        percent = max(percent, 75 + int(min(24, ratio * 25)))
    if failed:
        message = manager_msg or "编排失败"
        percent = min(percent, 25)
    elif step_workers:
        message = "编排完成，Worker 交互式终端应已弹出"
    elif step_assigned and assigned_children and not step_workers:
        message = f"正在启动 Worker 终端 ({len(spawned_for_assigned)}/{len(assigned_ids)})…"
    elif step_assigned and not assigned_children:
        message = f"已下发 {len(children)} 个子任务（含 blocked 依赖）"
    elif step_decomposed and not step_assigned:
        message = manager_msg or "拆解完成，正在写入子任务…"
    elif step_manager_running:
        message = manager_msg or "主管正在拆解…"
    elif step_created:
        message = "根任务已创建，等待主管进程…"
    else:
        message = manager_msg or "等待中…"

    return OrchestrationProgress(
        task_id=root_task_id,
        description=description,
        percent=min(100, max(0, percent)),
        message=message,
        steps=steps,
        done=done,
        failed=failed,
    )
