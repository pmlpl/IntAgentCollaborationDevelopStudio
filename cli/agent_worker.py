# cli/agent_worker.py — 在新终端窗口中运行的 Agent 工作进程
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from agents.runner import (
    agent_available,
    load_position,
    run_position_task,
    run_position_task_capture,
)
from core.config.agent_policy import agent_allowed, agent_can_execute, agent_enabled
from core.dispatch.decompose import (
    MARKER,
    _resolve_decompose_fallback,
    generate_mock_subtasks,
    parse_manager_output,
    save_decompose_result,
    validate_subtasks,
)
from core.dispatch.delivery import (
    REVIEW_MARKER,
    apply_manager_verdict,
    load_delivery_record,
    parse_manager_review_output,
)
from core.dispatch.review_compliance import compliance_for_task
from core.ipc.message_bus import MessageBus
from core.logging import get_logger
from core.org.tree_ops import OrgTree
from core.platform.skills_client import format_team_skills_line
from core.project import get_studio_root, load_project
from core.runtime.state import AgentRuntimeState, write_state

logger = get_logger(__name__)


def _ensure_utf8_stdout() -> None:
    """Force stdout/stderr to UTF-8, avoiding GBK crashes on Windows."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure") and (stream.encoding or "").lower() not in ("utf-8", "utf8"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _collect_ceo_feedback(project_dir: Path, manager_id: str) -> str:
    """从主管 inbox 中读取 CEO 反馈消息，格式化为 prompt 文本段。"""
    from datetime import datetime

    inbox_dir = project_dir / "agents" / manager_id / "inbox"
    bus = MessageBus(inbox_dir)
    feedback_msgs = [
        m for m in bus.peek()
        if m.type == "ceo_feedback" and m.sender == "__ceo__"
    ]
    if not feedback_msgs:
        return ""
    lines = ["## CEO Feedback (from the CEO during orchestration)"]
    for m in feedback_msgs:
        text = (m.payload or {}).get("text", "")
        try:
            t = datetime.fromisoformat(m.created_at.replace("Z", "+00:00"))
            ts = t.strftime("%H:%M")
        except (ValueError, AttributeError):
            ts = "??:??"
        lines.append(f'- [{ts}] "{text}"')
    return "\n".join(lines)


def _build_decompose_prompt(root: Path, project_dir: Path, manager_id: str, description: str) -> str:
    import yaml

    data = yaml.safe_load((project_dir / "positions.yaml").read_text(encoding="utf-8"))
    tree = OrgTree.from_yaml_data(data)
    team_lines = []
    for pos in data.get("positions", []):
        if pos["id"] == manager_id:
            continue
        resume = pos.get("resume") or {}
        strengths = resume.get("strengths") or []
        extra = format_team_skills_line(root, pos, tree=tree)
        team_lines.append(
            f"- {pos['name']} ({pos['title']}) id={pos['id']} "
            f"擅长={strengths} {extra}".strip()
        )
    team = "\n".join(team_lines)
    ceo_feedback = _collect_ceo_feedback(project_dir, manager_id)
    feedback_section = f"\n{ceo_feedback}\n\n" if ceo_feedback else "\n"
    return (
        f"You are the Tech Lead. CEO task: {description}\n\n"
        f"Team members (with registered skills/MCP):\n{team}\n"
        f"{feedback_section}"
        f"## Language Policy (IMPORTANT)\n"
        f"- ALL communication with team members MUST be in English\n"
        f"- Sub-task descriptions MUST be written in English\n"
        f"- When reporting final results to CEO, summarize in Chinese (中文)\n\n"
        f"## Parallel-first Principle (IMPORTANT)\n"
        f"- Tasks that can run concurrently MUST be dispatched together, waits_on set to []\n"
        f"- Only set waits_on when the task truly depends on prior output (code/files/decisions)\n"
        f"- If the team has N members, dispatch at least N sub-tasks simultaneously\n\n"
        f"## Output Requirements (MUST follow strictly)\n"
        f"1. First briefly list sub-task assignments in English (3-8 lines)\n"
        f"2. Then output the marker on its own line (must match exactly): {MARKER}\n"
        f"3. Starting from the line after the marker, output ONLY a JSON array (no markdown code blocks)\n"
        f"4. assignee must be one of the team member IDs listed above\n"
        f"5. Each item fields: assignee, description, waits_on (empty [] if no dependencies)\n"
        f"6. Example (for format reference only, use real assignee IDs):\n"
        f'[{{"assignee":"xiaohong","description":"Implement the frontend UI with Vue3 components...","waits_on":[]}}]'
    )


def _finish_with_mock(
    project_dir: Path,
    manager_id: str,
    agent_dir: Path,
    description: str,
    *,
    reason: str,
) -> int:
    subtasks = generate_mock_subtasks(project_dir, description)
    save_decompose_result(project_dir, manager_id, subtasks)
    write_state(
        agent_dir,
        AgentRuntimeState(
            status="submitted",
            progress=100,
            message=f"已用规则拆解（{reason}）",
        ),
    )
    print(f"{MARKER}\n{json.dumps(subtasks, ensure_ascii=False, indent=2)}")
    return 0


def cmd_decompose(args: argparse.Namespace) -> int:
    _ensure_utf8_stdout()
    root = Path(args.root).resolve()
    project_dir = load_project(root, args.project)
    manager_id = args.position
    agent_dir = project_dir / "agents" / manager_id

    write_state(
        agent_dir,
        AgentRuntimeState(status="working", progress=20, message="正在拆解任务…"),
    )

    inbox = MessageBus(agent_dir / "inbox")
    messages = inbox.drain()
    description = args.description
    for msg in messages:
        if msg.type == "task_decompose":
            description = msg.payload.get("description", description)

    force_mock = os.environ.get("STUDIO_MOCK", "").lower() in ("1", "true", "yes") or args.mock
    pos = load_position(project_dir, manager_id)
    agent_id = pos["agent"]
    can_run, reason = agent_can_execute(root, agent_id)

    if force_mock:
        return _finish_with_mock(
            project_dir, manager_id, agent_dir, description, reason="强制 mock 模式"
        )

    if not can_run:
        logger.info("decompose: agent %s cannot execute: %s, falling back to mock", agent_id, reason)
        return _finish_with_mock(
            project_dir, manager_id, agent_dir, description, reason=reason,
        )

    prompt = _build_decompose_prompt(root, project_dir, manager_id, description)
    try:
        rc, output = run_position_task_capture(
            root, project_dir, manager_id, prompt, mock=False
        )
    except FileNotFoundError as exc:
        if _resolve_decompose_fallback(project_dir) == "mock":
            subtasks = generate_mock_subtasks(project_dir, description)
            save_decompose_result(project_dir, manager_id, subtasks)
            write_state(
                agent_dir,
                AgentRuntimeState(
                    status="submitted",
                    progress=100,
                    message=f"Agent 启动失败已回退 mock: {exc}",
                ),
            )
            print(f"{MARKER}\n{json.dumps(subtasks, ensure_ascii=False, indent=2)}")
            return 0
        write_state(
            agent_dir,
            AgentRuntimeState(status="idle", progress=0, message=f"Agent 启动失败: {exc}"),
        )
        print(f"Agent 启动失败: {exc}", file=sys.stderr)
        return 1
    print(output)
    try:
        raw = parse_manager_output(output)
        subtasks = validate_subtasks(raw, project_dir, manager_id)
    except (ValueError, json.JSONDecodeError) as exc:
        fallback = _resolve_decompose_fallback(project_dir)
        if fallback == "mock":
            return _finish_with_mock(
                project_dir,
                manager_id,
                agent_dir,
                description,
                reason=f"Agent 输出解析失败: {exc}",
            )
        write_state(
            agent_dir,
            AgentRuntimeState(status="idle", progress=0, message=f"拆解解析失败: {exc}"),
        )
        return 1 if rc == 0 else rc

    save_decompose_result(project_dir, manager_id, subtasks)
    write_state(
        agent_dir,
        AgentRuntimeState(status="submitted", progress=100, message="拆解完成"),
    )
    return rc


def cmd_work(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    project_dir = load_project(root, args.project)
    position_id = args.position
    agent_dir = project_dir / "agents" / position_id

    inbox = MessageBus(agent_dir / "inbox")
    messages = inbox.drain()
    description = args.description or "执行任务"
    task_id = args.task_id
    for msg in messages:
        if msg.type == "task_assign":
            description = msg.payload.get("description", description)
            task_id = msg.task_id

    worktree = None
    if args.worktree:
        worktree = Path(args.worktree)

    force_mock = os.environ.get("STUDIO_MOCK", "").lower() in ("1", "true", "yes") or args.mock
    pos = load_position(project_dir, position_id)
    can_run, reason = _agent_can_execute(root, pos["agent"])
    use_mock = force_mock or not can_run

    if not can_run and not force_mock:
        logger.info("work: agent %s cannot execute: %s, falling back to mock", pos["agent"], reason)

    rc = run_position_task(
        root, project_dir, position_id, description, worktree=worktree, mock=use_mock
    )
    write_state(
        agent_dir,
        AgentRuntimeState(
            task_id=task_id,
            status="submitted" if rc == 0 else "idle",
            progress=100 if rc == 0 else 0,
            message="已提交" if rc == 0 else "执行失败",
        ),
    )
    return rc


def _build_review_prompt(root: Path, project_dir: Path, task_id: str, manager_id: str = "") -> str:
    """构建主管验收 Worker 交付的提示词。"""
    import yaml

    task_path = project_dir / "tasks" / "active" / f"{task_id}.yaml"
    if not task_path.is_file():
        raise FileNotFoundError(f"task not found: {task_id}")
    task = yaml.safe_load(task_path.read_text(encoding="utf-8"))
    record = load_delivery_record(project_dir, task_id) or {}
    summary = record.get("summary") or task.get("description", "")
    files = record.get("files") or []
    run_cmd = record.get("run_command") or "（未执行）"
    exit_code = record.get("exit_code", -1)
    run_output = str(record.get("run_output") or "")[:2000]
    assignee = task.get("assignee") or record.get("assignee") or "worker"

    # 防线三：技能合规检查清单
    compliance_text = compliance_for_task(root, project_dir, task_id)

    # CEO 反馈（如果有）
    ceo_feedback = _collect_ceo_feedback(project_dir, manager_id) if manager_id else ""
    feedback_section = f"\n{ceo_feedback}\n" if ceo_feedback else ""

    return (
        f"You are the Tech Lead reviewing a delivery from team member {assignee}.\n\n"
        f"Task ID: {task_id}\n"
        f"Delivery Summary: {summary}\n"
        f"{feedback_section}\n"
        f"Files: {', '.join(files) if files else '(none listed)'}\n"
        f"Auto-verification command: {run_cmd}\n"
        f"Exit code: {exit_code}\n"
        f"Run output:\n{run_output or '(none)'}\n\n"
        f"## Skills Compliance Checklist (review each item)\n"
        f"{compliance_text}\n\n"
        f"## Language Policy\n"
        f"- If you need to send feedback to the worker, write in English\n"
        f"- The final verdict comment for CEO MUST be in Chinese (中文)\n\n"
        f"Based on the run results, task objectives, and compliance checklist, "
        f"decide: approved / rejected / escalated.\n\n"
        f"## Output Requirements (MUST follow strictly)\n"
        f"1. First briefly explain your review conclusion in English (2-5 lines)\n"
        f"2. Then output the marker on its own line (must match exactly): {REVIEW_MARKER}\n"
        f"3. Starting from the line after the marker, output ONLY a JSON object (no markdown code blocks)\n"
        f"4. Fields: verdict (approved|rejected|escalated), comment (in Chinese 中文, for CEO)\n"
        f'5. Example: {{"verdict":"approved","comment":"功能完整，测试通过，代码质量良好，建议合并"}}'
    )


def _rule_based_review(record: dict) -> dict[str, str]:
    """Agent 不可用或解析失败时，按运行结果规则判定。"""
    exit_code = record.get("exit_code", -1)
    if exit_code == 0:
        return {"verdict": "approved", "comment": "自动验证通过（规则兜底）"}
    output = str(record.get("run_output") or "")[:200]
    return {
        "verdict": "rejected",
        "comment": f"自动验证未通过（exit={exit_code}）{output}",
    }


def cmd_review(args: argparse.Namespace) -> int:
    """主管审查 Worker 交付。"""
    _ensure_utf8_stdout()
    root = Path(args.root).resolve()
    project_dir = load_project(root, args.project)
    manager_id = args.position
    task_id = args.task_id
    agent_dir = project_dir / "agents" / manager_id

    if not task_id:
        print("缺少 --task-id", file=sys.stderr)
        return 1

    write_state(
        agent_dir,
        AgentRuntimeState(status="working", progress=50, message="正在审查交付…"),
    )

    record = load_delivery_record(project_dir, task_id) or {}
    force_mock = os.environ.get("STUDIO_MOCK", "").lower() in ("1", "true", "yes") or args.mock
    pos = load_position(project_dir, manager_id)
    can_run, reason = _agent_can_execute(root, pos["agent"])
    agent_ok = can_run

    if force_mock or not agent_ok:
        if not agent_ok and not force_mock:
            logger.info("review: agent %s cannot execute: %s, using rule-based review", pos["agent"], reason)

    if force_mock or not agent_ok:
        verdict_data = _rule_based_review(record)
        apply_manager_verdict(
            project_dir,
            task_id,
            verdict_data["verdict"],
            comment=verdict_data["comment"],
            manager_id=manager_id,
        )
        write_state(
            agent_dir,
            AgentRuntimeState(status="submitted", progress=100, message="审查完成（规则）"),
        )
        print(f"{REVIEW_MARKER}\n{json.dumps(verdict_data, ensure_ascii=False)}")
        return 0

    prompt = _build_review_prompt(root, project_dir, task_id, manager_id=manager_id)
    try:
        rc, output = run_position_task_capture(
            root, project_dir, manager_id, prompt, mock=False
        )
    except FileNotFoundError as exc:
        verdict_data = _rule_based_review(record)
        apply_manager_verdict(
            project_dir,
            task_id,
            verdict_data["verdict"],
            comment=f"{verdict_data['comment']}（Agent 启动失败: {exc}）",
            manager_id=manager_id,
        )
        write_state(
            agent_dir,
            AgentRuntimeState(status="submitted", progress=100, message="审查完成（规则）"),
        )
        print(f"{REVIEW_MARKER}\n{json.dumps(verdict_data, ensure_ascii=False)}")
        return 0

    print(output)
    parsed = parse_manager_review_output(output)
    if not parsed:
        parsed = _rule_based_review(record)
        parsed["comment"] = f"Agent 输出无法解析，规则兜底：{parsed['comment']}"

    apply_manager_verdict(
        project_dir,
        task_id,
        parsed["verdict"],
        comment=parsed.get("comment", ""),
        manager_id=manager_id,
    )
    write_state(
        agent_dir,
        AgentRuntimeState(status="submitted", progress=100, message="审查完成"),
    )
    return rc


def _try_work_from_inbox(
    root: Path,
    project_dir: Path,
    position_id: str,
    worktree: Path | None,
    *,
    mock: bool = False,
) -> int:
    """读取 inbox 中下一条 task_assign 消息并执行。无消息返回 0。"""
    agent_dir = project_dir / "agents" / position_id
    inbox = MessageBus(agent_dir / "inbox")
    messages = inbox.drain()
    for msg in messages:
        if msg.type == "task_assign":
            task_id = msg.task_id
            description = msg.payload.get("description", "")
            logger.info("watch: %s picked up task_assign %s", position_id, task_id)

            pos = load_position(project_dir, position_id)
            can_run, reason = _agent_can_execute(root, pos["agent"])
            use_mock = mock or not can_run
            if not can_run and not mock:
                logger.info("watch: agent %s cannot execute: %s, falling back to mock", pos["agent"], reason)

            rc = run_position_task(
                root, project_dir, position_id, description,
                worktree=worktree, mock=use_mock,
            )
            write_state(
                agent_dir,
                AgentRuntimeState(
                    task_id=task_id,
                    status="submitted" if rc == 0 else "idle",
                    progress=100 if rc == 0 else 0,
                    message="已提交" if rc == 0 else "执行失败",
                ),
            )
            return 0
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    """Worker 持续运行模式：执行初始任务后轮询 inbox，复用同一进程/终端。"""
    _ensure_utf8_stdout()
    import time as _time

    root = Path(args.root).resolve()
    project_dir = load_project(root, args.project)
    position_id = args.position

    worktree = None
    if args.worktree:
        worktree = Path(args.worktree)

    force_mock = os.environ.get("STUDIO_MOCK", "").lower() in ("1", "true", "yes") or args.mock
    pos = load_position(project_dir, position_id)
    can_run, reason = _agent_can_execute(root, pos["agent"])
    use_mock = force_mock or not can_run

    # 注册 PID
    task_id = args.task_id or ""
    _pid_path = Path.home() / ".studio" / "agent_pids.json"
    import json as _json
    from datetime import datetime, timezone as _tz
    _pid_path.parent.mkdir(parents=True, exist_ok=True)
    pids: dict = {}
    if _pid_path.is_file():
        try:
            pids = _json.loads(_pid_path.read_text(encoding="utf-8"))
        except _json.JSONDecodeError:
            pass
    pids[position_id] = {
        "pid": os.getpid(),
        "task_id": task_id,
        "worktree": str(worktree or ""),
        "project": args.project,
        "spawned_at": datetime.now(_tz.utc).isoformat(),
    }
    _pid_path.write_text(_json.dumps(pids, ensure_ascii=False, indent=2), encoding="utf-8")

    # 执行初始任务（若有）
    if args.description and args.description != "等待任务…":
        rc = run_position_task(
            root, project_dir, position_id, args.description,
            worktree=worktree, mock=use_mock,
        )
    else:
        _try_work_from_inbox(root, project_dir, position_id, worktree, mock=use_mock)

    # 轮询 inbox
    POLL_INTERVAL = 5  # 秒
    print(f"[watch] {position_id} 等待新任务 (PID={os.getpid()})…")
    try:
        while True:
            _time.sleep(POLL_INTERVAL)
            # 刷新 PID 注册（证明自己还活着）
            if _pid_path.is_file():
                try:
                    pids = _json.loads(_pid_path.read_text(encoding="utf-8"))
                except _json.JSONDecodeError:
                    pids = {}
                if position_id in pids:
                    pids[position_id]["last_seen"] = datetime.now(_tz.utc).isoformat()
                    _pid_path.write_text(_json.dumps(pids, ensure_ascii=False, indent=2), encoding="utf-8")

            _try_work_from_inbox(root, project_dir, position_id, worktree, mock=use_mock)
    except KeyboardInterrupt:
        # 退出时清理 PID 注册
        if _pid_path.is_file():
            try:
                pids = _json.loads(_pid_path.read_text(encoding="utf-8"))
            except _json.JSONDecodeError:
                pids = {}
            pids.pop(position_id, None)
            _pid_path.write_text(_json.dumps(pids, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[watch] {position_id} 已退出")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent_worker")
    sub = parser.add_subparsers(dest="mode", required=True)

    p_dec = sub.add_parser("decompose", help="主管拆解任务")
    p_dec.add_argument("--root", default=str(get_studio_root()))
    p_dec.add_argument("--project", required=True)
    p_dec.add_argument("--position", required=True)
    p_dec.add_argument("--task-id", default=None)
    p_dec.add_argument("--description", default="")
    p_dec.add_argument("--mock", action="store_true", help="强制 mock 拆解")
    p_dec.set_defaults(func=cmd_decompose)

    p_work = sub.add_parser("work", help="Worker 执行任务")
    p_work.add_argument("--root", default=str(get_studio_root()))
    p_work.add_argument("--project", required=True)
    p_work.add_argument("--position", required=True)
    p_work.add_argument("--task-id", default=None)
    p_work.add_argument("--description", default="")
    p_work.add_argument("--worktree", default=None)
    p_work.add_argument("--mock", action="store_true", help="强制 mock 执行")
    p_work.set_defaults(func=cmd_work)

    p_rev = sub.add_parser("review", help="主管审查 Worker 交付")
    p_rev.add_argument("--root", default=str(get_studio_root()))
    p_rev.add_argument("--project", required=True)
    p_rev.add_argument("--position", required=True)
    p_rev.add_argument("--task-id", required=True)
    p_rev.add_argument("--mock", action="store_true", help="强制规则审查")
    p_rev.set_defaults(func=cmd_review)

    p_watch = sub.add_parser("watch", help="Worker 持续运行模式：轮询 inbox 复用会话")
    p_watch.add_argument("--root", default=str(get_studio_root()))
    p_watch.add_argument("--project", required=True)
    p_watch.add_argument("--position", required=True)
    p_watch.add_argument("--task-id", default=None)
    p_watch.add_argument("--description", default="等待任务…")
    p_watch.add_argument("--worktree", default=None)
    p_watch.add_argument("--mock", action="store_true", help="强制 mock 执行")
    p_watch.set_defaults(func=cmd_watch)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
