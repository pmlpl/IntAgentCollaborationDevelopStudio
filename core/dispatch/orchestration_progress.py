# core/dispatch/orchestration_progress.py — 任务编排进度（覆盖完整生命周期）
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.dispatch.decompose import load_decompose_result
from core.dispatch.delivery import load_delivery_record
from core.runtime.state import AgentRuntimeState, read_state


@dataclass
class OrchestrationStep:
    """编排流水线中的单步。"""

    label: str
    done: bool
    active: bool = False
    detail: str = ""


@dataclass
class OrchestrationProgress:
    """当前根任务的编排进度（覆盖 创建→拆解→执行→交付→审查→归档）。"""

    task_id: str
    description: str
    percent: int
    message: str
    steps: list[OrchestrationStep] = field(default_factory=list)
    done: bool = False
    failed: bool = False
    # 动态计数
    total_children: int = 0
    delivered_count: int = 0
    reviewed_count: int = 0
    archived_count: int = 0


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
    path = project_dir / "tasks" / "active" / f".workers-{root_task_id}.json"
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return set(data if isinstance(data, list) else [])
    except json.JSONDecodeError:
        return set()


def _manager_on_root_task(state: AgentRuntimeState, root_task_id: str) -> bool:
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
    """Compute real-time orchestration progress across 6 lifecycle phases.

    Phases (with dynamic % ranges):
      1. 创建根任务       (5-10%)
      2. 主管拆解中       (10-30%)  — tracks manager agent progress
      3. 子任务分配启动   (30-45%)  — subtasks written, workers spawning
      4. Worker 执行交付  (45-65%)  — tracks DELIVER.json arrival
      5. 主管审查验收     (65-85%)  — tracks review verdicts
      6. 完成归档         (85-100%) — all children terminal
    """
    manager_id = _root_manager_id(project_dir)
    manager_dir = project_dir / "agents" / manager_id
    manager_state = (
        states.get(manager_id) if states else read_state(manager_dir)
    )
    if manager_state is None:
        manager_state = read_state(manager_dir)

    active_dir = project_dir / "tasks" / "active"
    archive_dir = project_dir / "tasks" / "archive"
    if tasks is None:
        import yaml
        tasks = []
        for d in (active_dir, archive_dir):
            if d.exists():
                for path in sorted(d.glob("*.yaml")):
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

    # ── Count children by status ──
    total_children = len(children)
    # Delivered: tasks with status in_review or that have a non-empty delivery record
    delivered_ids: set[str] = set()
    reviewed_ids: set[str] = set()
    archived_ids: set[str] = set()
    rejected_ids: set[str] = set()

    for child in children:
        cid = str(child.get("id") or "")
        cstatus = str(child.get("status") or "")
        if cstatus in ("in_review",):
            delivered_ids.add(cid)
        elif cstatus in ("archived",):
            archived_ids.add(cid)
        elif cstatus in ("rejected",):
            rejected_ids.add(cid)
        elif cstatus in ("assigned", "in_progress", "submitted"):
            # Check if there's a delivery record (worker may have delivered
            # but status not yet updated by poll cycle)
            record = load_delivery_record(project_dir, cid)
            if record and (record.get("summary") or record.get("files")):
                delivered_ids.add(cid)

    # Tasks that have a review marker are being reviewed
    for child in children:
        cid = str(child.get("id") or "")
        cstatus = str(child.get("status") or "")
        if cid in archived_ids or cid in rejected_ids:
            reviewed_ids.add(cid)
        elif cid in delivered_ids and cstatus == "in_review":
            # Being actively reviewed
            pass
        elif cstatus == "archived":
            reviewed_ids.add(cid)

    # reviewed = archived + rejected (decisions made)
    reviewed_ids = archived_ids | rejected_ids

    delivered_count = len(delivered_ids | archived_ids | rejected_ids)
    reviewed_count = len(reviewed_ids)
    archived_count = len(archived_ids)

    # ── Determine phase states ──
    on_task = _manager_on_root_task(manager_state, root_task_id)
    manager_msg = (manager_state.message or "").strip()

    step_created = root_task is not None
    step_decomposing = (
        step_created
        and on_task
        and manager_state.status == "working"
        and decompose is None
    )
    step_decomposed = decompose is not None
    step_assigned = len(children) > 0
    step_workers_spawned = (
        step_assigned
        and len(assigned_children) > 0
        and len(spawned_for_assigned) >= len(assigned_ids)
    ) or (step_assigned and not assigned_children)  # all blocked counts as spawned
    step_any_delivered = delivered_count > 0
    step_all_delivered = total_children > 0 and delivered_count >= total_children
    step_any_reviewed = reviewed_count > 0
    step_all_reviewed = total_children > 0 and reviewed_count >= total_children
    step_all_archived = total_children > 0 and archived_count >= total_children

    # ── Failure detection ──
    failed = (
        on_task
        and manager_state.status == "idle"
        and (
            manager_msg.startswith("拆解解析失败")
            or "执行失败" in manager_msg
            or manager_msg.startswith("Agent 启动失败")
        )
    )

    # ── Build steps ──
    steps = [
        OrchestrationStep(
            "1. 创建根任务",
            done=step_created,
            active=False,
            detail=root_task_id if step_created else "",
        ),
        OrchestrationStep(
            "2. 主管拆解中",
            done=step_decomposed,
            active=step_decomposing and not failed,
            detail=manager_msg if step_decomposing else ("拆解完成" if step_decomposed else ""),
        ),
        OrchestrationStep(
            "3. 子任务分配启动",
            done=step_workers_spawned,
            active=step_decomposed and not step_workers_spawned and not failed,
            detail=(
                f"{len(spawned_for_assigned)}/{len(assigned_ids)} Worker 已启动"
                if assigned_children
                else f"{total_children} 个子任务（含阻塞依赖）"
            ) if step_assigned else "",
        ),
        OrchestrationStep(
            "4. Worker 执行交付",
            done=step_all_delivered,
            active=step_workers_spawned and not step_all_delivered and not failed,
            detail=(
                f"{delivered_count}/{total_children} 已交付"
                if total_children > 0
                else ""
            ),
        ),
        OrchestrationStep(
            "5. 主管审查验收",
            done=step_all_reviewed,
            active=step_any_delivered and not step_all_reviewed and not failed,
            detail=(
                f"{reviewed_count}/{delivered_count} 已审查"
                if delivered_count > 0
                else ""
            ),
        ),
        OrchestrationStep(
            "6. 完成归档",
            done=step_all_archived,
            active=step_all_reviewed and not step_all_archived and not failed,
            detail=f"{archived_count}/{total_children} 已归档" if total_children > 0 else "",
        ),
    ]

    # ── Compute percent dynamically ──
    percent = 0
    if failed:
        percent = max(5, 25 if step_decomposed else 10)
        message = manager_msg or "编排失败"
    elif step_all_archived:
        percent = 100
        message = f"全部完成 — {archived_count}/{total_children} 子任务已归档"
    elif step_all_reviewed:
        percent = 90
        message = f"审查完毕，{archived_count} 已归档"
    elif step_all_delivered:
        # 75-85%: all delivered, some reviewed
        if total_children > 0:
            ratio = reviewed_count / total_children
            percent = 75 + int(ratio * 10)
        else:
            percent = 75
        message = f"全部交付，{reviewed_count}/{total_children} 已审查"
    elif step_workers_spawned:
        # 45-75%: workers executing, tracking deliveries
        if total_children > 0:
            ratio = delivered_count / total_children
            percent = 45 + int(ratio * 30)
        else:
            percent = 45
        if delivered_count > 0:
            message = f"Worker 执行中 — {delivered_count}/{total_children} 已交付"
        else:
            message = f"Worker 执行中 — 等待交付（{total_children} 个 Worker）"
    elif step_assigned:
        # 30-45%: subtasks assigned, workers being spawned
        if assigned_children and assigned_ids:
            ratio = len(spawned_for_assigned) / len(assigned_ids)
            percent = 30 + int(ratio * 15)
        else:
            percent = 35
        message = f"正在启动 Worker 终端 ({len(spawned_for_assigned)}/{len(assigned_ids)})"
    elif step_decomposed and not step_assigned:
        percent = 28
        message = manager_msg or "拆解完成，正在写入子任务…"
    elif step_decomposing:
        # 10-28%: manager working
        mgr_progress = max(0, min(100, manager_state.progress))
        percent = 10 + int(mgr_progress * 18 / 100)
        message = manager_msg or "主管正在拆解…"
    elif step_created:
        percent = 5
        message = "根任务已创建，等待主管进程…"
    else:
        percent = 0
        message = manager_msg or "等待中…"

    # ── Done condition: all children archived (or all reviewed with no active work) ──
    done = step_all_archived or (step_all_reviewed and archived_count >= total_children)

    return OrchestrationProgress(
        task_id=root_task_id,
        description=description,
        percent=min(100, max(0, percent)),
        message=message,
        steps=steps,
        done=done,
        failed=failed,
        total_children=total_children,
        delivered_count=delivered_count,
        reviewed_count=reviewed_count,
        archived_count=archived_count,
    )
