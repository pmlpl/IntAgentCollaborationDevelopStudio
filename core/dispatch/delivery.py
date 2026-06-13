# core/dispatch/delivery.py — Worker 交付扫描、运行验证、主管审查
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from core.ipc.message_bus import Message, MessageBus
from core.logging import get_logger

logger = get_logger(__name__)

DELIVER_REL = Path(".studio") / "DELIVER.json"
REVIEW_MARKER = "---STUDIO_REVIEW_JSON---"
PROCESSED_SUFFIX = ".processed"


def deliver_path(worktree: Path) -> Path:
    return worktree / DELIVER_REL


def find_deliver_files(project_dir: Path, project_root: Path | None = None) -> list[Path]:
    """扫描项目目录与各 worktree 下的 DELIVER.json。"""
    seen: set[Path] = set()
    roots: list[Path] = [project_dir.resolve()]
    if project_root and project_root.resolve() != project_dir.resolve():
        roots.append(project_root.resolve())
    ws = project_dir / "workspaces"
    if ws.is_dir():
        for child in ws.iterdir():
            if child.is_dir():
                roots.append(child.resolve())

    out: list[Path] = []
    for root in roots:
        path = root / DELIVER_REL
        if path.is_file() and path not in seen:
            seen.add(path)
            out.append(path)
    return out


def load_deliver_payload(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def resolve_worktree_from_deliver(deliver_path: Path, project_dir: Path, project_root: Path | None) -> Path:
    """从 DELIVER.json 路径推断代码所在 worktree（项目根或 workspaces 子目录）。"""
    parent = deliver_path.parent
    if parent.name != ".studio":
        return parent.resolve()
    wt = parent.parent.resolve()
    if project_root and wt == project_dir.resolve():
        return project_root.resolve()
    return wt


def infer_run_command(worktree: Path, deliver: dict[str, Any]) -> str:
    """Worker 未写 run_command 时，根据交付文件推断验证命令。"""
    explicit = str(deliver.get("run_command") or "").strip()
    if explicit:
        return explicit
    files = [str(f) for f in (deliver.get("files") or [])]
    test_hint = str(deliver.get("test_results") or "").lower()
    test_files = [f for f in files if f.startswith("test_") and f.endswith(".py")]
    if test_files or "passed" in test_hint or "pytest" in test_hint:
        if len(test_files) == 1:
            return f"python -m pytest {test_files[0]} -q"
        if test_files:
            return "python -m pytest -q"
        for entry in worktree.iterdir():
            if entry.is_file() and entry.name.startswith("test_") and entry.suffix == ".py":
                return f"python -m pytest {entry.name} -q"
    for name in ("main.py", "app.py", "index.py"):
        if name in files or (worktree / name).is_file():
            return f"python {name}"
    py_main = [f for f in files if f.endswith(".py") and not f.startswith("test_")]
    if len(py_main) == 1:
        return f"python {py_main[0]}"
    return ""


def run_deliver_command(worktree: Path, command: str) -> tuple[int, str]:
    """在 worktree 内执行交付声明的运行命令（无 shell，安全拆分参数）。"""
    if not command.strip():
        return -1, "未提供 run_command"

    # 安全拆分 command 字符串为 argv（避免 shell=True 注入风险）
    argv = _safe_parse_command(command)
    if not argv:
        return -1, "无法解析 run_command"

    try:
        result = subprocess.run(
            argv,
            cwd=worktree,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        output = (result.stdout or "") + (result.stderr or "")
        return result.returncode, output.strip()[:4000]
    except subprocess.TimeoutExpired:
        return -1, "运行超时（120s）"
    except OSError as exc:
        return -1, str(exc)


def _safe_parse_command(command: str) -> list[str] | None:
    """将 shell 命令字符串安全拆分为 argv 列表。

    仅支持简单的 command arg1 arg2... 格式；
    不支持管道、重定向等 shell 特性（这些本就不该出现在 DELIVER.json 中）。
    返回 None 表示命令格式不安全。
    """
    import shlex

    # 拒绝明显危险的 shell 元字符
    dangerous = {"|", ";", "&", "`", "$(", "${", "<", ">", "&&", "||"}
    for ch in dangerous:
        if ch in command:
            return None

    try:
        argv = shlex.split(command.strip())
    except ValueError:
        return None

    if not argv:
        return None
    return argv


def build_ceo_dispatch_brief(goal: str, notes: str = "") -> str:
    """CEO 仅下达业务目标；技术拆解由主管负责。"""
    lines = ["【CEO 目标】", goal.strip(), ""]
    if notes.strip():
        lines.extend(["【CEO 补充】", notes.strip(), ""])
    lines.append(
        "请主管据此拆解子任务，自行补充 MVP 范围、实现路径、验收标准，并分配给团队。"
    )
    return "\n".join(lines)


def save_delivery_record(project_dir: Path, task_id: str, record: dict[str, Any]) -> Path:
    path = project_dir / "tasks" / "active" / f".delivery-{task_id}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_delivery_record(project_dir: Path, task_id: str) -> dict[str, Any] | None:
    path = project_dir / "tasks" / "active" / f".delivery-{task_id}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _mark_deliver_processed(path: Path) -> None:
    done = path.with_name(path.name + PROCESSED_SUFFIX)
    if not done.exists():
        path.rename(done)


def _update_task(project_dir: Path, task_id: str, **fields: Any) -> dict[str, Any] | None:
    task_path = project_dir / "tasks" / "active" / f"{task_id}.yaml"
    if not task_path.is_file():
        return None
    task = yaml.safe_load(task_path.read_text(encoding="utf-8"))
    task.update(fields)
    task["updated_at"] = datetime.now(timezone.utc).isoformat()
    task_path.write_text(yaml.dump(task, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return task


def process_worker_delivery(
    project_dir: Path,
    task: dict[str, Any],
    deliver: dict[str, Any],
    worktree: Path,
    *,
    manager_id: str,
) -> dict[str, Any]:
    """Worker 交付 → 运行验证 → 待主管审查。

    防御：空交付（无文件/无摘要/无 run_command）不推断执行命令，
    避免误运行 curses 等终端交互程序破坏 TUI。
    """
    task_id = str(task.get("id") or deliver.get("task_id") or "")
    assignee = str(
        task.get("assignee") or deliver.get("assignee") or deliver.get("worker") or ""
    )

    has_files = bool(deliver.get("files") or [])
    has_summary = bool(str(deliver.get("summary") or "").strip())
    has_explicit_run = bool(str(deliver.get("run_command") or "").strip())
    is_empty_deliver = not has_files and not has_summary and not has_explicit_run

    run_cmd = "" if is_empty_deliver else infer_run_command(worktree, deliver)
    exit_code = -1
    run_output = ""
    if run_cmd:
        exit_code, run_output = run_deliver_command(worktree, run_cmd)
    elif deliver.get("run_ok") is True:
        exit_code = 0
        run_output = "Worker 声明 run_ok=true（未提供 run_command）"

    record = {
        "task_id": task_id,
        "assignee": assignee,
        "summary": str(deliver.get("summary") or ""),
        "files": list(deliver.get("files") or []),
        "run_command": run_cmd,
        "exit_code": exit_code,
        "run_output": run_output,
        "received_at": datetime.now(timezone.utc).isoformat(),
    }
    save_delivery_record(project_dir, task_id, record)

    _update_task(project_dir, task_id, status="in_review")
    bus = MessageBus(project_dir / "agents" / manager_id / "inbox")
    bus.deliver(
        Message(
            id=Message.new_id(),
            type="review_request",
            sender=assignee,
            recipient=manager_id,
            task_id=task_id,
            payload={
                "summary": record["summary"],
                "exit_code": exit_code,
                "run_command": run_cmd,
                "run_output": run_output[:800],
            },
            trace=["ceo", manager_id, assignee],
        )
    )
    return record


def apply_manager_verdict(
    project_dir: Path,
    task_id: str,
    verdict: str,
    *,
    comment: str = "",
    manager_id: str = "laowang",
) -> dict[str, Any] | None:
    """主管审查结论：通过 / 打回 / 上报 CEO。"""
    if verdict not in ("approved", "rejected", "escalated"):
        raise ValueError(f"invalid verdict: {verdict}")

    task_path = project_dir / "tasks" / "active" / f"{task_id}.yaml"
    if not task_path.is_file():
        return None
    task = yaml.safe_load(task_path.read_text(encoding="utf-8"))
    assignee = str(task.get("assignee") or "")

    if verdict == "approved":
        task["status"] = "archived"
        # 尝试合并 worktree
        _try_merge_worktree(project_dir, task_id, assignee)
        archive = project_dir / "tasks" / "archive" / f"{task_id}.yaml"
        archive.parent.mkdir(parents=True, exist_ok=True)
        task["review_comment"] = comment
        task["updated_at"] = datetime.now(timezone.utc).isoformat()
        archive.write_text(yaml.dump(task, allow_unicode=True, sort_keys=False), encoding="utf-8")
        task_path.unlink()
    elif verdict == "rejected":
        task["status"] = "assigned"
        task["review_comment"] = comment
        task["updated_at"] = datetime.now(timezone.utc).isoformat()
        task_path.write_text(yaml.dump(task, allow_unicode=True, sort_keys=False), encoding="utf-8")
        if assignee:
            bus = MessageBus(project_dir / "agents" / assignee / "inbox")
            bus.deliver(
                Message(
                    id=Message.new_id(),
                    type="task_assign",
                    sender=manager_id,
                    recipient=assignee,
                    task_id=task_id,
                    payload={"description": task.get("description", ""), "feedback": comment},
                    trace=["ceo", manager_id],
                )
            )
    else:
        task["status"] = "escalated"
        task["review_comment"] = comment
        task["updated_at"] = datetime.now(timezone.utc).isoformat()
        task_path.write_text(yaml.dump(task, allow_unicode=True, sort_keys=False), encoding="utf-8")
        bus = MessageBus(project_dir / "agents" / "__ceo__" / "inbox")
        bus.deliver(
            Message(
                id=Message.new_id(),
                type="ceo_review",
                sender=manager_id,
                recipient="__ceo__",
                task_id=task_id,
                payload={"summary": comment or task.get("description", "")},
                trace=["ceo", manager_id],
            )
        )
    return task


def _try_merge_worktree(project_dir: Path, task_id: str, assignee: str) -> None:
    """approved 后尝试将 worktree 合并回主分支。失败则通知 CEO。"""
    import yaml as _yaml

    from core.workspace.worktree import WorktreeManager

    ws_root = project_dir / "workspaces"
    repo_yaml = project_dir / "shared" / "repo.yaml"
    if not repo_yaml.exists() or not ws_root.exists():
        return
    meta = _yaml.safe_load(repo_yaml.read_text(encoding="utf-8"))
    repo_path = Path(meta.get("repo_path", ""))
    if not repo_path.exists():
        return

    candidates = [d for d in ws_root.iterdir() if d.is_dir() and d.name.startswith(task_id)]
    if not candidates:
        return

    mgr = WorktreeManager(repo_path, ws_root)
    for wt in candidates:
        try:
            result = mgr.merge(wt.name)
            if result["merged"]:
                logger.info("merged worktree %s for task %s", wt.name, task_id)
            else:
                ceo_bus = MessageBus(project_dir / "agents" / "__ceo__" / "inbox")
                conflicts = result.get("conflicts", [])
                ceo_bus.deliver(
                    Message(
                        id=Message.new_id(),
                        type="ceo_review",
                        sender="system",
                        recipient="__ceo__",
                        task_id=task_id,
                        payload={
                            "summary": f"合并冲突: {wt.name} → {conflicts}",
                            "detail": f"分支 {result.get('branch')} 合并失败，需人工处理",
                        },
                        trace=["system"],
                    )
                )
        except Exception as exc:
            logger.warning("worktree merge failed for %s: %s", wt.name, exc)


def parse_manager_review_output(stdout: str) -> dict[str, Any] | None:
    """解析主管审查 Agent 输出。"""
    if not stdout.strip():
        return None
    if REVIEW_MARKER in stdout:
        chunk = stdout.split(REVIEW_MARKER)[-1].strip()
    else:
        chunk = stdout.strip()
    start = chunk.find("{")
    if start < 0:
        return None
    try:
        data, _ = json.JSONDecoder().raw_decode(chunk[start:])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    verdict = str(data.get("verdict") or "").strip().lower()
    if verdict not in ("approved", "rejected", "escalated"):
        return None
    return {"verdict": verdict, "comment": str(data.get("comment") or "")}


def poll_worker_deliveries(
    project_dir: Path,
    *,
    manager_id: str,
    project_root: Path | None = None,
) -> list[dict[str, Any]]:
    """扫描新 DELIVER.json 并登记为 in_review。"""
    tasks = {}
    active = project_dir / "tasks" / "active"
    if active.is_dir():
        for path in active.glob("*.yaml"):
            t = yaml.safe_load(path.read_text(encoding="utf-8"))
            if t.get("id"):
                tasks[str(t["id"])] = t

    processed: list[dict[str, Any]] = []
    for path in find_deliver_files(project_dir, project_root):
        if path.name.endswith(PROCESSED_SUFFIX):
            continue
        deliver = load_deliver_payload(path)
        if not deliver:
            continue
        task_id = str(deliver.get("task_id") or "")
        task = tasks.get(task_id)
        if not task:
            continue
        if task.get("status") in ("archived", "in_review", "escalated"):
            _mark_deliver_processed(path)
            continue
        worktree = resolve_worktree_from_deliver(path, project_dir, project_root)
        record = process_worker_delivery(
            project_dir, task, deliver, worktree, manager_id=manager_id
        )
        _mark_deliver_processed(path)
        processed.append(record)
    return processed


def refresh_delivery_verification(
    project_dir: Path,
    task_id: str,
    *,
    project_root: Path | None = None,
) -> dict[str, Any] | None:
    """对已登记但尚未成功跑验证的交付记录补跑 run_command。

    防御：空记录 / 无实质交付内容时不重跑，避免触发终端交互程序。
    """
    record = load_delivery_record(project_dir, task_id)
    if not record or record.get("exit_code", -1) >= 0:
        return record
    run_cmd = str(record.get("run_command") or "").strip()
    # 若记录无实质内容（无文件/无摘要/无 run_command），不回补执行
    has_files = bool(record.get("files") or [])
    has_summary = bool(str(record.get("summary") or "").strip())
    if not run_cmd and not has_files and not has_summary:
        return record
    worktree = (project_root or project_dir.parent).resolve()
    if not run_cmd:
        deliver_stub = {
            "files": record.get("files") or [],
            "test_results": record.get("test_results") or "",
        }
        run_cmd = infer_run_command(worktree, deliver_stub)
    if not run_cmd:
        return record
    exit_code, run_output = run_deliver_command(worktree, run_cmd)
    record["run_command"] = run_cmd
    record["exit_code"] = exit_code
    record["run_output"] = run_output
    save_delivery_record(project_dir, task_id, record)
    return record
