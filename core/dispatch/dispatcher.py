# core/dispatch/dispatcher.py — 任务创建、路由、编排与状态查询
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from core.dispatch.decompose import (
    apply_subtasks,
    generate_mock_subtasks,
    get_ready_subtasks,
    load_decompose_result,
    save_decompose_result,
)
from core.dispatch.delivery import (
    generate_mock_delivery,
    poll_worker_deliveries,
    refresh_delivery_verification,
)
from core.ipc.message_bus import Message, MessageBus
from core.config.agent_policy import agent_allowed, agent_enabled
from core.logging import get_logger
from core.org.tree_ops import OrgTree
from core.project import get_project_root, load_project
from core.runtime.state import AgentRuntimeState, write_state
from core.supervisor_client import SupervisorClient
from core.terminal.agent_launcher import spawn_worker_agent_terminal
from core.terminal.spawner import spawn_python_module

logger = get_logger(__name__)
from core.workspace.worktree import WorktreeManager


def _slugify(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")
    return slug[:40] or "task"


def _orchestration_settings(root: Path) -> dict[str, Any]:
    """读取 platform.yaml 中的 orchestration 段。"""
    path = root / "config" / "platform.yaml"
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    orch = data.get("orchestration")
    return orch if isinstance(orch, dict) else {}


def _spawn_decompose_background(module_args: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    """后台运行主管拆解（不弹 Windows Terminal 窗口）。"""
    merged = os.environ.copy()
    merged.update(env)
    cmd = [sys.executable, "-m", *module_args]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    subprocess.Popen(cmd, cwd=cwd, env=merged, creationflags=flags)


class Dispatcher:
    """任务调度器。"""

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir.resolve()
        self.positions_path = self.project_dir / "positions.yaml"
        self.tasks_active = self.project_dir / "tasks" / "active"
        self.tasks_archive = self.project_dir / "tasks" / "archive"
        self._tree: OrgTree | None = None
        # 防止同一秒内重复 spawn 同一 Worker（Dashboard 可能连续触发两次 try_complete）
        self._worker_spawn_inflight: set[str] = set()
        # 记录当前编排是否使用 mock 模式（begin_orchestration 设置，后续流程读取）
        self._auto_mock: bool = False
        # 记录上次 spawn 尝试时间，防止短时间重复触发
        self._last_spawn_attempt: float = 0.0

    @property
    def project_name(self) -> str:
        data = yaml.safe_load(self.positions_path.read_text(encoding="utf-8"))
        return data.get("project", self.project_dir.name)

    def _load_tree(self) -> OrgTree:
        if self._tree is None:
            data = yaml.safe_load(self.positions_path.read_text(encoding="utf-8"))
            self._tree = OrgTree.from_yaml_data(data)
        return self._tree

    def _root_manager_id(self) -> str:
        tree = self._load_tree()
        managers = tree.root_managers()
        if not managers:
            raise RuntimeError("no root manager (parent=null, is_manager=true)")
        return managers[0]

    def _inbox_bus(self, position_id: str) -> MessageBus:
        inbox = self.project_dir / "agents" / position_id / "inbox"
        return MessageBus(inbox)

    def _repo_path(self, root: Path) -> Path | None:
        repo_yaml = self.project_dir / "shared" / "repo.yaml"
        if repo_yaml.exists():
            meta = yaml.safe_load(repo_yaml.read_text(encoding="utf-8"))
            return Path(meta["repo_path"])
        return root

    def list_positions(self) -> list[dict[str, Any]]:
        data = yaml.safe_load(self.positions_path.read_text(encoding="utf-8"))
        return data.get("positions", [])

    def create_task(self, description: str) -> dict[str, Any]:
        """创建根任务并投递 task_decompose 到主管 inbox。"""
        task_id = f"task-{uuid.uuid4().hex[:8]}"
        manager_id = self._root_manager_id()
        logger.info("create_task: %s -> manager=%s desc=%s", task_id, manager_id, description[:80])
        now = datetime.now(timezone.utc).isoformat()
        task: dict[str, Any] = {
            "id": task_id,
            "description": description,
            "status": "pending",
            "assignee": manager_id,
            "created_at": now,
            "updated_at": now,
            "slug": _slugify(description),
        }
        task_path = self.tasks_active / f"{task_id}.yaml"
        task_path.write_text(
            yaml.dump(task, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )

        msg = Message(
            id=Message.new_id(),
            type="task_decompose",
            sender="__ceo__",
            recipient=manager_id,
            task_id=task_id,
            payload={"description": description},
            trace=["ceo"],
        )
        self._inbox_bus(manager_id).deliver(msg)
        return task

    def begin_orchestration(
        self,
        root: Path,
        description: str,
        *,
        spawn_terminals: bool = True,
        mock: bool = False,
    ) -> dict[str, Any]:
        """创建任务并启动主管拆解（新终端或 mock）。

        如果 Agent 不可用或被禁用，自动降级为 mock 模式。"""
        task = self.create_task(description)
        manager_id = self._root_manager_id()
        self._update_task_status(task["id"], "in_progress")

        # 检测主管 Agent 是否可执行
        pos = self._position_by_id(manager_id)
        agent_id = pos.get("agent", "")
        agent_can_run = (
            agent_id
            and agent_enabled(root, agent_id)
            and agent_allowed(root, agent_id)
        )
        auto_mock = mock or not agent_can_run
        self._auto_mock = auto_mock  # 记录状态供后续 try_complete_orchestration 使用
        if auto_mock and not mock:
            reason = "Agent 未安装或被禁用" if not agent_can_run else "手动 mock"
            logger.info("begin_orchestration: auto-mock (reason=%s, agent=%s)", reason, agent_id)

        env = {"STUDIO_MOCK": "1"} if auto_mock else {}
        if auto_mock:
            subtasks = generate_mock_subtasks(self.project_dir, description)
            save_decompose_result(self.project_dir, manager_id, subtasks)
        supervisor = SupervisorClient(root)
        supervisor.ensure_running()
        if spawn_terminals and not auto_mock:
            pos = self._position_by_id(manager_id)
            orch = _orchestration_settings(root)
            show_manager_terminal = bool(orch.get("spawn_manager_terminal", False))
            write_state(
                self.project_dir / "agents" / manager_id,
                AgentRuntimeState(
                    task_id=task["id"],
                    status="working",
                    progress=5,
                    message="正在启动主管拆解…",
                ),
            )
            title = f"Studio · {pos.get('name', manager_id)} · 主管"
            module_args = [
                "cli.agent_worker",
                "decompose",
                "--root",
                str(root),
                "--project",
                self.project_name,
                "--position",
                manager_id,
                "--task-id",
                task["id"],
                "--description",
                description,
            ]
            if show_manager_terminal:
                spawn_python_module(
                    title,
                    module_args,
                    cwd=root,
                    env=env,
                )
                progress_msg = "主管终端已启动，等待拆解…"
            else:
                _spawn_decompose_background(module_args, cwd=root, env=env)
                progress_msg = "主管后台拆解中…"
            write_state(
                self.project_dir / "agents" / manager_id,
                AgentRuntimeState(
                    task_id=task["id"],
                    status="working",
                    progress=15,
                    message=progress_msg,
                ),
            )
        return task

    def _orchestration_marker(self, root_task_id: str) -> Path:
        return self.tasks_active / f".orchestrated-{root_task_id}.json"

    def _workers_spawned_path(self, root_task_id: str) -> Path:
        return self.tasks_active / f".workers-{root_task_id}.json"

    def _load_spawned_worker_ids(self, root_task_id: str) -> set[str]:
        path = self._workers_spawned_path(root_task_id)
        if not path.exists():
            return set()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return set(data if isinstance(data, list) else [])
        except json.JSONDecodeError:
            return set()

    def _save_spawned_worker_id(self, root_task_id: str, subtask_id: str) -> None:
        path = self._workers_spawned_path(root_task_id)
        spawned = self._load_spawned_worker_ids(root_task_id)
        spawned.add(subtask_id)
        path.write_text(
            json.dumps(sorted(spawned), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def try_complete_orchestration(
        self,
        root: Path,
        root_task_id: str,
        *,
        spawn_terminals: bool = True,
        mock: bool | None = None,
    ) -> bool:
        """若主管拆解完成，则下发子任务并 spawn Worker Claude 终端（spawn 可重试）。"""
        # 未显式传入 mock 时，沿用 begin_orchestration 记录的 _auto_mock 状态
        if mock is None:
            mock = self._auto_mock
        manager_id = self._root_manager_id()
        subtasks = load_decompose_result(self.project_dir, manager_id)
        if subtasks is None:
            return False

        marker = self._orchestration_marker(root_task_id)
        root_task = self._load_task(root_task_id)
        children = [
            t for t in self.get_status() if t.get("parent_id") == root_task_id
        ]
        # 仅在首次编排且无子任务时 apply，避免子任务全归档后重复创建
        if not children and not marker.exists():
            apply_subtasks(
                self.project_dir,
                root_task_id,
                subtasks,
                root_task.get("description", ""),
                manager_id=manager_id,
            )
            self._update_task_status(root_task_id, "assigned")

        if not marker.exists():
            marker.write_text(
                json.dumps({"completed": True}, ensure_ascii=False), encoding="utf-8"
            )

        # 每次轮询都尝试 spawn 尚未启动的 Worker（此前 marker 过早写入会导致永不重试）
        # mock 模式：无视 spawn_terminals，始终同步执行 Worker+审查闭环
        if spawn_terminals or mock:
            self._spawn_ready_workers(root, root_task_id, mock=mock)

        return True

    def _run_mock_workers_and_review(self, root: Path, root_task_id: str) -> None:
        """Mock 模式：同步模拟 Worker 执行 → 交付 → 审查 → 归档。

        为每个 assigned Worker 在独立的 mock worktree 目录写入 DELIVER.json，
        通过 poll_worker_deliveries 统一扫描处理，再行规则审查，
        完成全流程闭环。
        """
        from core.dispatch.delivery import (
            DELIVER_REL,
            apply_manager_verdict,
            find_deliver_files,
            load_delivery_record,
            load_deliver_payload,
            process_worker_delivery,
        )

        manager_id = self._root_manager_id()
        project_root = self._repo_path(root) or self.project_dir

        # 收集 assigned Worker 并构建任务索引
        tasks_by_id: dict[str, dict] = {}
        assigned_workers: list[dict] = []
        for p in sorted(self.tasks_active.glob("*.yaml")):
            task = yaml.safe_load(p.read_text(encoding="utf-8"))
            tid = str(task.get("id") or "")
            if tid:
                tasks_by_id[tid] = task
            if task.get("parent_id") != root_task_id:
                continue
            if task.get("status") == "assigned":
                assigned_workers.append(task)

        if not assigned_workers:
            logger.warning("mock workers: no assigned workers found for %s", root_task_id)
            return

        # 为每个 Worker 在独立目录写入 DELIVER.json（避免路径冲突）
        for task in assigned_workers:
            sub_id = str(task.get("id") or "")
            assignee = str(task.get("assignee") or "")
            description = str(task.get("description") or "")

            # 每个 Worker 独立的 mock worktree
            mock_wt = self.project_dir / "workspaces" / f"{sub_id}-mock"
            mock_wt.mkdir(parents=True, exist_ok=True)
            studio_dir = mock_wt / ".studio"
            studio_dir.mkdir(parents=True, exist_ok=True)

            deliver_path = studio_dir / "DELIVER.json"
            from core.dispatch.delivery import generate_mock_delivery as _gen_deliver
            deliver = _gen_deliver(
                self.project_dir, sub_id, assignee, description
            )
            deliver_path.write_text(
                json.dumps(deliver, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info("mock worker: %s (%s) wrote DELIVER.json", sub_id, assignee)

        # 扫描并处理所有交付（复用统一的 poll → process → review 链路）
        for deliver_path in find_deliver_files(self.project_dir, project_root):
            if deliver_path.name.endswith(".processed"):
                continue
            deliver = load_deliver_payload(deliver_path)
            if not deliver:
                continue
            task_id = str(deliver.get("task_id") or "")
            task = tasks_by_id.get(task_id)
            if not task:
                continue
            if task.get("status") in ("archived", "in_review", "escalated"):
                continue
            worktree = deliver_path.parent.parent  # .studio/DELIVER.json → parent=.studio → parent=worktree
            process_worker_delivery(
                self.project_dir, task, deliver, worktree, manager_id=manager_id
            )
            # 标记已处理
            done = deliver_path.with_name(deliver_path.name + ".processed")
            if not done.exists():
                deliver_path.rename(done)

            # 规则审查（同步 inline，不 spawn 后台进程）
            record = load_delivery_record(self.project_dir, task_id) or {}
            exit_code = record.get("exit_code", -1)
            run_ok = record.get("run_output", "").startswith("Worker") if exit_code == 0 else False
            verdict = "approved" if (exit_code == 0 or run_ok) else "rejected"
            comment = (
                "[mock] 自动验证通过" if verdict == "approved"
                else f"[mock] 验证未通过 (exit={exit_code})"
            )
            logger.info("mock review: %s → %s (%s)", task_id, verdict, comment)
            apply_manager_verdict(
                self.project_dir, task_id, verdict, comment=comment,
                manager_id=manager_id,
            )

        # 检查依赖后继续派发被解除阻塞的任务
        self._unblock_ready_tasks()

        # 若 active 中不再有该编排的子任务，根任务归档
        remaining_children = [
            p for p in self.tasks_active.glob("*.yaml")
            if yaml.safe_load(p.read_text(encoding="utf-8")).get("parent_id") == root_task_id
        ]
        if not remaining_children:
            self._update_task_status(root_task_id, "archived")

    def _remove_spawned_worker_id(self, root_task_id: str, subtask_id: str) -> None:
        """spawn 失败时撤销记录，便于下次轮询重试。"""
        spawned = self._load_spawned_worker_ids(root_task_id)
        if subtask_id not in spawned:
            return
        spawned.discard(subtask_id)
        path = self._workers_spawned_path(root_task_id)
        if spawned:
            path.write_text(
                json.dumps(sorted(spawned), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        elif path.exists():
            path.unlink()

    def _spawn_ready_workers(
        self, root: Path, root_task_id: str, *, mock: bool = False
    ) -> None:
        """为 assigned 状态的 worker 创建 worktree 并 spawn 交互式 Agent 终端。

        mock 模式：同步执行 Worker → 交付 → 审查 → 归档，跑完全流程闭环。
        """
        if mock:
            self._run_mock_workers_and_review(root, root_task_id)
            return

        # 速率限制：距上次尝试 2 秒内不重复执行，避免 Dashboard 高频触发
        import time
        now = time.time()
        if now - self._last_spawn_attempt < 2.0:
            return
        self._last_spawn_attempt = now

        repo = self._repo_path(root)
        project_root = get_project_root(root, self.project_name)
        ws_root = self.project_dir / "workspaces"
        mgr = WorktreeManager(repo, ws_root) if repo and (repo / ".git").exists() else None
        spawned = self._load_spawned_worker_ids(root_task_id)

        for path in sorted(self.tasks_active.glob("*.yaml")):
            task = yaml.safe_load(path.read_text(encoding="utf-8"))
            if task.get("parent_id") != root_task_id:
                continue
            if task.get("status") != "assigned":
                continue
            sub_id = str(task.get("id") or "")
            if sub_id in spawned or sub_id in self._worker_spawn_inflight:
                continue

            assignee = task["assignee"]
            pos = self._position_by_id(assignee)

            # PID-Aware: 若该 Agent 进程还活着，push inbox 而非 spawn 新终端
            from core.terminal.agent_launcher import is_agent_process_alive

            if is_agent_process_alive(assignee):
                logger.info(
                    "worker %s PID alive, pushing to inbox instead of spawn", assignee
                )
                bus = MessageBus(self.project_dir / "agents" / assignee / "inbox")
                bus.deliver(
                    Message(
                        id=Message.new_id(),
                        type="task_assign",
                        sender="__system__",
                        recipient=assignee,
                        task_id=sub_id,
                        payload={"description": str(task.get("description", ""))},
                        trace=["system", "pid-reuse"],
                    )
                )
                self._save_spawned_worker_id(root_task_id, sub_id)
                continue

            worktree_path = project_root
            if mgr:
                try:
                    # P0-B: 持久 worktree per agent，复用保留缓存
                    worktree_path = mgr.get_or_create_persistent(assignee)
                except Exception:
                    worktree_path = project_root

            title = f"Studio · {pos.get('name', assignee)} · {pos.get('title', '')}"
            # 先占位，避免同一轮询内重复开两个 Agent 窗口
            self._worker_spawn_inflight.add(sub_id)
            self._save_spawned_worker_id(root_task_id, sub_id)
            try:
                spawn_worker_agent_terminal(
                    root,
                    self.project_dir,
                    assignee,
                    str(task.get("description", "")),
                    worktree_path,
                    title=title,
                    task_id=sub_id,
                )
            except Exception:
                # 任何异常都撤销占位，允许下次轮询重试
                logger.warning(
                    "spawn worker %s failed, will retry", sub_id, exc_info=True
                )
                self._remove_spawned_worker_id(root_task_id, sub_id)
            finally:
                self._worker_spawn_inflight.discard(sub_id)

    def _position_by_id(self, position_id: str) -> dict[str, Any]:
        for pos in self.list_positions():
            if pos["id"] == position_id:
                return pos
        return {"id": position_id, "name": position_id}

    def _load_task(self, task_id: str) -> dict[str, Any]:
        path = self.tasks_active / f"{task_id}.yaml"
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    def _update_task_status(self, task_id: str, status: str) -> None:
        path = self.tasks_active / f"{task_id}.yaml"
        if not path.exists():
            return
        task = yaml.safe_load(path.read_text(encoding="utf-8"))
        task["status"] = status
        task["updated_at"] = datetime.now(timezone.utc).isoformat()
        path.write_text(
            yaml.dump(task, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )

    def get_agent_states(self) -> dict[str, AgentRuntimeState]:
        from core.runtime.state import read_state

        states: dict[str, AgentRuntimeState] = {}
        for pos in self.list_positions():
            pid = pos["id"]
            states[pid] = read_state(self.project_dir / "agents" / pid)
        return states

    def get_status(self) -> list[dict[str, Any]]:
        tasks: list[dict[str, Any]] = []
        if not self.tasks_active.exists():
            return tasks
        for path in sorted(self.tasks_active.glob("*.yaml")):
            tasks.append(yaml.safe_load(path.read_text(encoding="utf-8")))
        return tasks

    def get_pending_reviews(self) -> list[dict[str, Any]]:
        """CEO 待审批：仅主管上报 escalated 的项。"""
        return [t for t in self.get_status() if t.get("status") == "escalated"]

    def get_manager_reviews(self) -> list[dict[str, Any]]:
        """主管待审查：Worker 已交付、等待验收。"""
        return [t for t in self.get_status() if t.get("status") == "in_review"]

    def poll_deliveries(self, root: Path) -> list[dict[str, Any]]:
        """扫描 Worker 的 DELIVER.json 并触发主管审查流程 + 自动解除依赖阻塞。"""
        manager_id = self._root_manager_id()
        project_root = self._repo_path(root)
        records = poll_worker_deliveries(
            self.project_dir,
            manager_id=manager_id,
            project_root=project_root,
        )
        for task in self.get_manager_reviews():
            tid = str(task.get("id") or "")
            if tid:
                refresh_delivery_verification(
                    self.project_dir, tid, project_root=project_root
                )
        if records or self.get_manager_reviews():
            self.try_run_manager_reviews(root)
        # 自动解除依赖阻塞
        self._unblock_ready_tasks()
        return records

    def _unblock_ready_tasks(self) -> list[str]:
        """检查 blocked 任务，满足依赖则自动解除并通知 Worker。"""
        ready = get_ready_subtasks(self.project_dir)
        if not ready:
            return []
        unblocked: list[str] = []
        for task in ready:
            task_id = str(task.get("id") or "")
            assignee = str(task.get("assignee") or "")
            task["status"] = "assigned"
            task["updated_at"] = datetime.now(timezone.utc).isoformat()
            task_path = self.tasks_active / f"{task_id}.yaml"
            task_path.write_text(
                yaml.dump(task, allow_unicode=True, sort_keys=False), encoding="utf-8"
            )
            # 通知 Worker
            if assignee:
                bus = MessageBus(self.project_dir / "agents" / assignee / "inbox")
                bus.deliver(
                    Message(
                        id=Message.new_id(),
                        type="task_assign",
                        sender="__system__",
                        recipient=assignee,
                        task_id=task_id,
                        payload={"description": task.get("description", "")},
                        trace=["system", "unblock"],
                    )
                )
            unblocked.append(task_id)
        if unblocked:
            logger.info("unblocked %d tasks: %s", len(unblocked), unblocked)
        return unblocked

    def _review_marker(self, task_id: str) -> Path:
        return self.tasks_active / f".review-started-{task_id}.json"

    def try_run_manager_reviews(self, root: Path, *, spawn: bool = True) -> None:
        """对 in_review 任务启动主管后台审查（每任务仅一次）。

        防御：交付记录为空或不存在时跳过，避免 Agent 误判需重新执行验证命令。
        过期标记清理：若审查标记超过 10 分钟未完成，清理并重试（进程可能已崩溃）。
        """
        import time as _time
        from core.dispatch.delivery import load_delivery_record

        REVIEW_STALE_SECONDS = 600  # 10 分钟过期

        manager_id = self._root_manager_id()
        for task in self.get_manager_reviews():
            task_id = str(task.get("id") or "")
            if not task_id:
                continue
            marker = self._review_marker(task_id)
            if marker.exists():
                # 检查标记是否过期（审查进程可能已崩溃）
                try:
                    age = _time.time() - marker.stat().st_mtime
                    if age > REVIEW_STALE_SECONDS:
                        marker.unlink()
                        logger.warning("review marker for %s is stale (%.0fs), cleared for retry", task_id, age)
                    else:
                        continue
                except OSError:
                    continue
            # 交付记录无实质内容时跳过，避免 Agent 尝试重新运行交付命令
            record = load_delivery_record(self.project_dir, task_id)
            if not record:
                continue
            has_files = bool(record.get("files") or [])
            has_summary = bool(str(record.get("summary") or "").strip())
            if not has_files and not has_summary:
                continue
            if spawn:
                marker.write_text("{}", encoding="utf-8")
                module_args = [
                    "cli.agent_worker",
                    "review",
                    "--root",
                    str(root),
                    "--project",
                    self.project_name,
                    "--position",
                    manager_id,
                    "--task-id",
                    task_id,
                ]
                _spawn_decompose_background(module_args, cwd=root, env={})

    def submit_review(self, task_id: str, verdict: str) -> dict[str, Any]:
        from core.dispatch.delivery import apply_manager_verdict

        manager_id = self._root_manager_id()
        task = apply_manager_verdict(
            self.project_dir,
            task_id,
            verdict,
            manager_id=manager_id,
        )
        if task is None:
            raise FileNotFoundError(f"task not found: {task_id}")
        return task


def get_dispatcher(root: Path, project: str | None = None) -> Dispatcher:
    project_dir = load_project(root, project)
    return Dispatcher(project_dir)
