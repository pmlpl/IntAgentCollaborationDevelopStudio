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
from core.dispatch.delivery import poll_worker_deliveries, refresh_delivery_verification
from core.ipc.message_bus import Message, MessageBus
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
        """创建任务并启动主管拆解（新终端或 mock）。"""
        task = self.create_task(description)
        manager_id = self._root_manager_id()
        self._update_task_status(task["id"], "in_progress")

        env = {"STUDIO_MOCK": "1"} if mock else {}
        if mock:
            subtasks = generate_mock_subtasks(self.project_dir, description)
            save_decompose_result(self.project_dir, manager_id, subtasks)
        supervisor = SupervisorClient(root)
        supervisor.ensure_running()
        if spawn_terminals and not mock:
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
        mock: bool = False,
    ) -> bool:
        """若主管拆解完成，则下发子任务并 spawn Worker Claude 终端（spawn 可重试）。"""
        manager_id = self._root_manager_id()
        subtasks = load_decompose_result(self.project_dir, manager_id)
        if subtasks is None:
            return False

        marker = self._orchestration_marker(root_task_id)
        root_task = self._load_task(root_task_id)
        children = [
            t for t in self.get_status() if t.get("parent_id") == root_task_id
        ]
        if not children:
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
        if spawn_terminals:
            self._spawn_ready_workers(root, root_task_id, mock=mock)

        return True

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
        """为 assigned 状态的 worker 创建 worktree 并 spawn 交互式 Agent 终端。"""
        if mock:
            return

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
            worktree_path = project_root
            if mgr:
                slug = task["id"].replace(root_task_id + "-", "")
                try:
                    worktree_path = mgr.create(task["id"], slug[:20])
                except Exception:
                    worktree_path = project_root

            title = f"Studio · {pos.get('name', assignee)} · {pos.get('title', '')}"
            # 先占位，避免同一轮询内重复开两个 Claude 窗口
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
            except RuntimeError:
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
        """扫描 Worker 的 DELIVER.json 并触发主管审查流程。"""
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
        return records

    def _review_marker(self, task_id: str) -> Path:
        return self.tasks_active / f".review-started-{task_id}.json"

    def try_run_manager_reviews(self, root: Path, *, spawn: bool = True) -> None:
        """对 in_review 任务启动主管后台审查（每任务仅一次）。"""
        manager_id = self._root_manager_id()
        for task in self.get_manager_reviews():
            task_id = str(task.get("id") or "")
            if not task_id or self._review_marker(task_id).exists():
                continue
            if spawn:
                self._review_marker(task_id).write_text("{}", encoding="utf-8")
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
