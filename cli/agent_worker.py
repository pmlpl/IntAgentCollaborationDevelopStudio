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
from core.config.agent_policy import agent_allowed, agent_enabled
from core.dispatch.decompose import (
    MARKER,
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
    return (
        f"你是技术主管。CEO 任务：{description}\n\n"
        f"团队成员（含已注册 skills/MCP）：\n{team}\n\n"
        f"拆分任务时，在子任务 description 里点名各成员应使用的 skills。\n\n"
        f"## 并行优先原则（重要）\n"
        f"- 能同时进行的任务必须同时派发，waits_on 留空 []\n"
        f"- 只有真正依赖前序产出（代码/文件/决策）时才设置 waits_on\n"
        f"- 若团队有 N 个成员，至少派发 N 个子任务同时开工\n\n"
        f"## 输出要求（必须严格遵守）\n"
        f"1. 先用中文简要列出子任务分工（3-8 行即可）\n"
        f"2. 然后单独一行输出标记（必须完全一致）：{MARKER}\n"
        f"3. 标记下一行起只输出 JSON 数组，不要 markdown 代码块\n"
        f"4. assignee 必须是上方团队成员的 id 字段\n"
        f"5. 每项字段：assignee, description, waits_on（无依赖则 []）\n"
        f"6. 示例（仅格式参考，assignee 请换成真实 id）：\n"
        f'[{{"assignee":"xiaohong","description":"...","waits_on":[]}}]'
    )


def _decompose_fallback_mode(root: Path) -> str:
    """解析失败时的策略：mock 自动拆解 | fail 直接报错。"""
    if os.environ.get("STUDIO_MOCK_FALLBACK", "").lower() in ("1", "true", "yes"):
        return "mock"
    path = root / "config" / "platform.yaml"
    if not path.is_file():
        return "mock"
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    orch = data.get("orchestration") or {}
    mode = str(orch.get("decompose_fallback", "mock")).strip().lower()
    return mode if mode in ("mock", "fail") else "mock"


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


def _agent_can_execute(root: Path, agent_id: str) -> tuple[bool, str]:
    """检查 Agent 是否可以真正执行任务。

    返回 (can_execute, reason)。
    can_execute=False 时 reason 说明原因。
    """
    if not agent_available(root, agent_id):
        return False, f"CLI 命令不在 PATH 中"
    if not agent_enabled(root, agent_id):
        return False, "已被用户禁用"
    if not agent_allowed(root, agent_id):
        return False, "当前 BYOK 策略不允许"
    return True, "ok"


def cmd_decompose(args: argparse.Namespace) -> int:
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
    can_run, reason = _agent_can_execute(root, agent_id)

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
        if _decompose_fallback_mode(root) == "mock":
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
        fallback = _decompose_fallback_mode(root)
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


def _build_review_prompt(root: Path, project_dir: Path, task_id: str) -> str:
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

    return (
        f"你是技术主管，正在验收团队成员 {assignee} 的交付。\n\n"
        f"任务 ID：{task_id}\n"
        f"交付摘要：{summary}\n"
        f"涉及文件：{', '.join(files) if files else '（未列出）'}\n"
        f"自动验证命令：{run_cmd}\n"
        f"退出码：{exit_code}\n"
        f"运行输出：\n{run_output or '（无）'}\n\n"
        f"## 技能合规检查清单（审查时必须逐项确认）\n"
        f"{compliance_text}\n\n"
        f"请根据运行结果、任务目标与合规清单判断：通过 / 打回修改 / 上报 CEO。\n\n"
        f"## 输出要求（必须严格遵守）\n"
        f"1. 先用中文简要说明审查结论（2-5 行）\n"
        f"2. 然后单独一行输出标记（必须完全一致）：{REVIEW_MARKER}\n"
        f"3. 标记下一行起只输出 JSON 对象，不要 markdown 代码块\n"
        f'4. 字段：verdict（approved|rejected|escalated）、comment（说明）\n'
        f'5. 示例：{{"verdict":"approved","comment":"测试通过，可合并"}}'
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

    prompt = _build_review_prompt(root, project_dir, task_id)
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

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
