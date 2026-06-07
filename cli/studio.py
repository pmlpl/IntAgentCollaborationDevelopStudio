# cli/studio.py — Studio CLI 主入口
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core.dispatch.dispatcher import get_dispatcher
from core.project import get_studio_root, init_project, load_project, set_current_project
from core.supervisor_client import SupervisorClient


def cmd_init(args: argparse.Namespace) -> int:
    root = get_studio_root()
    SupervisorClient(root).ensure_running()
    project_dir = init_project(root, args.name, repo_path=Path(args.repo) if args.repo else None)
    set_current_project(root, args.name)
    print(f"✓ 项目已创建: {project_dir}")
    print(f"  组织: {project_dir / 'positions.yaml'}")
    return 0


def cmd_task(args: argparse.Namespace) -> int:
    root = get_studio_root()
    SupervisorClient(root).ensure_running()
    disp = get_dispatcher(root, args.project)
    task = disp.create_task(args.description)
    print(f"✓ 任务已创建: {task['id']}")
    print(f"  状态: {task['status']}")
    print(f"  主管 inbox 已收到 task_decompose 消息")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    root = get_studio_root()
    disp = get_dispatcher(root, args.project)
    tasks = disp.get_status()
    if not tasks:
        print("暂无进行中的任务。")
        return 0
    for task in tasks:
        bar = "█" * 5 + "░" * 5
        print(f"  {task['id']}  {bar}  {task['status']}  {task['description'][:40]}")
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    root = get_studio_root()
    disp = get_dispatcher(root, args.project)
    pending = disp.get_pending_reviews()
    if not pending:
        print("暂无待审批项。")
        return 0
    for i, task in enumerate(pending, 1):
        print(f"  [{i}] {task['id']} — {task['description'][:60]} ({task['status']})")
    if args.verdict and args.task_id:
        result = disp.submit_review(args.task_id, args.verdict)
        print(f"✓ 任务 {args.task_id} → {result['status']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="studio", description="IntAgent 协作开发管理平台")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="创建新项目")
    p_init.add_argument("--name", required=True, help="项目名")
    p_init.add_argument("--repo", default=None, help="Git 仓库路径")
    p_init.set_defaults(func=cmd_init)

    p_task = sub.add_parser("task", help="下达任务")
    p_task.add_argument("description", help="任务描述")
    p_task.add_argument("--project", default=None)
    p_task.set_defaults(func=cmd_task)

    p_status = sub.add_parser("status", help="查看进度")
    p_status.add_argument("--project", default=None)
    p_status.set_defaults(func=cmd_status)

    p_review = sub.add_parser("review", help="审批")
    p_review.add_argument("--project", default=None)
    p_review.add_argument("--task-id", default=None)
    p_review.add_argument("--verdict", choices=["approved", "rejected", "escalated"], default=None)
    p_review.set_defaults(func=cmd_review)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
