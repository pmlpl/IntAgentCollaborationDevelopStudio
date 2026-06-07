# core/dispatch/dispatcher.py — 任务创建、路由与状态查询
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from core.ipc.message_bus import Message, MessageBus
from core.org.tree_ops import OrgTree
from core.project import load_project


def _slugify(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")
    return slug[:40] or "task"


class Dispatcher:
    """任务调度器。"""

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir.resolve()
        self.positions_path = self.project_dir / "positions.yaml"
        self.tasks_active = self.project_dir / "tasks" / "active"
        self.tasks_archive = self.project_dir / "tasks" / "archive"
        self._tree: OrgTree | None = None

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

    def create_task(self, description: str) -> dict[str, Any]:
        """创建根任务并投递 task_decompose 到主管 inbox。"""
        task_id = f"task-{uuid.uuid4().hex[:8]}"
        manager_id = self._root_manager_id()
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

    def get_status(self) -> list[dict[str, Any]]:
        """返回所有 active 任务状态。"""
        tasks: list[dict[str, Any]] = []
        if not self.tasks_active.exists():
            return tasks
        for path in sorted(self.tasks_active.glob("*.yaml")):
            task = yaml.safe_load(path.read_text(encoding="utf-8"))
            tasks.append(task)
        return tasks

    def get_pending_reviews(self) -> list[dict[str, Any]]:
        """返回 escalated 或 in_review 待 CEO 处理的任务。"""
        return [
            t
            for t in self.get_status()
            if t.get("status") in ("escalated", "in_review")
        ]

    def submit_review(self, task_id: str, verdict: str) -> dict[str, Any]:
        """CEO 审批：approved / rejected / escalated。"""
        task_path = self.tasks_active / f"{task_id}.yaml"
        if not task_path.exists():
            raise FileNotFoundError(f"task not found: {task_id}")
        task = yaml.safe_load(task_path.read_text(encoding="utf-8"))
        if verdict not in ("approved", "rejected", "escalated"):
            raise ValueError(f"invalid verdict: {verdict}")
        task["status"] = verdict if verdict != "approved" else "archived"
        task["updated_at"] = datetime.now(timezone.utc).isoformat()
        if verdict == "approved":
            archive_path = self.tasks_archive / f"{task_id}.yaml"
            archive_path.write_text(
                yaml.dump(task, allow_unicode=True, sort_keys=False), encoding="utf-8"
            )
            task_path.unlink()
        else:
            task_path.write_text(
                yaml.dump(task, allow_unicode=True, sort_keys=False), encoding="utf-8"
            )
        return task


def get_dispatcher(root: Path, project: str | None = None) -> Dispatcher:
    project_dir = load_project(root, project)
    return Dispatcher(project_dir)
