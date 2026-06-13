# core/dispatch/decompose.py — 主管拆解结果解析与子任务下发
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from core.ipc.message_bus import Message, MessageBus
from core.logging import get_logger

logger = get_logger(__name__)

MARKER = "---STUDIO_SUBTASKS_JSON---"


def _strip_markdown_fence(text: str) -> str:
    """去掉 ```json ... ``` 包裹。"""
    text = text.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _repair_truncated_json(text: str) -> str | None:
    """尝试修复被截断的 JSON。

    - 截断的数组：补回缺失的 ]
    - 截断的对象：补回缺失的 }
    - 尾部多余的非 JSON 文字：切除
    返回修复后的文本，或 None 表示无法修复。
    """
    text = text.strip()
    if not text:
        return None

    # 1. 切除尾部 markdown 或解释文字（找最后一个合法的 JSON 结束符）
    for closer in ("}]", "}]}", '"]', '"]}'):
        idx = text.rfind(closer)
        if idx > 0:
            text = text[: idx + len(closer)]
            break

    # 2. 补回缺失的括号
    if text.startswith("[") and not text.rstrip().endswith("]"):
        # 数组截断：检查是否有未闭合的 {
        open_braces = text.count("{") - text.count("}")
        suffix = "}" * max(0, open_braces) + "]"
        text = text.rstrip() + suffix
    elif text.startswith("{") and not text.rstrip().endswith("}"):
        open_braces = text.count("{") - text.count("}")
        text = text.rstrip() + "}" * max(0, open_braces)

    return text


def _parse_with_retry(
    manager_fn,
    project_dir: Path,
    manager_id: str,
    task_description: str,
    *,
    max_retries: int = 2,
    mock: bool = False,
) -> list[dict[str, Any]]:
    """执行主管拆解并解析输出，解析失败时最多重试 max_retries 次。

    每次重试时会给主管 Agent 回传错误信息，让它重新输出。
    全部失败则根据 platform.yaml 的 decompose_fallback 决定走 mock 还是报错。
    """
    from core.config.agent_policy import agent_enabled as cfg_agent_enabled
    from agents.runner import run_position_task_capture

    last_error = ""
    root = _find_studio_root(project_dir)

    for attempt in range(max_retries + 1):
        if attempt == 0:
            rc, stdout = run_position_task_capture(
                root, project_dir, manager_id, task_description, mock=mock,
            )
        else:
            # 重试：把错误信息回传给主管
            retry_prompt = (
                f"上一次你输出的 JSON 格式有误（{last_error}）。\n"
                f"请严格按以下格式重新输出（只输出 JSON，不要加解释）：\n"
                f"{MARKER}\n"
                f'[{{"assignee":"...","description":"...","waits_on":[]}}]\n\n'
                f"原始任务：{task_description}"
            )
            rc, stdout = run_position_task_capture(
                root, project_dir, manager_id, retry_prompt, mock=mock,
            )

        if rc != 0:
            last_error = f"Agent 退出码 {rc}"
            continue

        try:
            result = parse_manager_output(stdout)
            if attempt > 0:
                logger.info("_parse_with_retry: succeeded on attempt %d", attempt + 1)
            return result
        except ValueError as exc:
            last_error = str(exc)
            logger.warning("_parse_with_retry: attempt %d failed: %s", attempt + 1, last_error)

    # 全部重试失败：走 fallback
    _ = _resolve_decompose_fallback(project_dir)
    if _ == "mock":
        logger.warning("_parse_with_retry: all attempts failed, falling back to mock")
        return generate_mock_subtasks(project_dir, task_description)
    raise ValueError(f"主管拆解解析失败（重试{max_retries}次后）: {last_error}")


def _resolve_decompose_fallback(project_dir: Path) -> str:
    """读取 platform.yaml 的 orchestration.decompose_fallback 策略。"""
    import os as _os

    if _os.environ.get("STUDIO_MOCK_FALLBACK", "").lower() in ("1", "true", "yes"):
        return "mock"

    # 从 .studio/ 往上找项目根，再定位 config/platform.yaml
    studio_root = _find_studio_root(project_dir)
    cfg_path = studio_root / "config" / "platform.yaml"
    if not cfg_path.exists():
        return "mock"

    try:
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return "mock"

    orch = data.get("orchestration") or {}
    fallback = str(orch.get("decompose_fallback", "mock")).strip().lower()
    if fallback in ("mock", "raise", "error"):
        return fallback
    return "mock"


def _find_studio_root(path: Path) -> Path:
    """从 .studio/ 目录往上找到 studio 项目根。

    到达项目目录（包含 .studio/ 的目录）后取其父目录（即 projects/ 的父目录）。
    """
    # 找到包含 .studio/ 的项目数据目录
    for p in [path] + list(path.parents):
        if (p / ".studio").is_dir():
            # p 是项目数据目录（如 projects/xxx/.studio），根是 p.parent.parent
            # 即 projects/ 的父目录 → 到达含 config/ 和 projects/ 的仓库根
            candidate = p.parent.parent
            if (candidate / "config" / "platform.yaml").exists():
                return candidate
            # 降级：尝试 p.parent
            if (p.parent / "config" / "platform.yaml").exists():
                return p.parent
            break
    # 最终降级：用 path 往上找任意包含 config/platform.yaml 的目录
    for p in [path] + list(path.parents):
        if (p / "config" / "platform.yaml").exists():
            return p
    return path


def _coerce_subtask_list(items: list[Any]) -> list[dict[str, Any]] | None:
    """过滤出含 assignee 字段的对象列表。"""
    out: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict) and item.get("assignee"):
            out.append(item)
    return out or None


def _extract_subtask_objects(text: str) -> list[dict[str, Any]] | None:
    """从混杂文本中扫描含 assignee 的 JSON 对象（Agent 未输出 marker 时的兜底）。"""
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in re.finditer(r"\{", text):
        chunk = text[match.start() :]
        try:
            obj, _end = json.JSONDecoder().raw_decode(chunk)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict) or not obj.get("assignee"):
            continue
        key = str(obj.get("assignee"))
        if key in seen:
            continue
        seen.add(key)
        found.append(obj)
    return found or None


def _try_parse_subtasks_json(text: str) -> list[dict[str, Any]] | None:
    """尝试把字符串解析为子任务 JSON 数组。"""
    text = _strip_markdown_fence(text.strip())
    if not text:
        return None
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return _coerce_subtask_list(data)
        if isinstance(data, dict):
            for key in ("subtasks", "tasks", "items", "assignments"):
                inner = data.get(key)
                if isinstance(inner, list):
                    return _coerce_subtask_list(inner)
    except json.JSONDecodeError:
        pass
    start = text.find("[")
    if start < 0:
        return None
    try:
        data, _end = json.JSONDecoder().raw_decode(text[start:])
        if isinstance(data, list):
            return _coerce_subtask_list(data)
    except json.JSONDecodeError:
        return None
    return None


def parse_manager_output(stdout: str) -> list[dict[str, Any]]:
    """从主管 stdout 解析子任务 JSON 列表（兼容 marker 重复、代码块、JSON 在 marker 前）。"""
    if not stdout.strip():
        logger.warning("parse_manager_output: empty stdout")
        raise ValueError("empty manager output")

    candidates: list[str] = []

    if MARKER in stdout:
        # 取最后一次 marker 之后（Claude 常在文末输出；避免误匹配 prompt 示例）
        candidates.append(stdout.split(MARKER)[-1])

    for match in re.finditer(r"```(?:json)?\s*(\[[\s\S]*?\])\s*```", stdout, flags=re.I):
        candidates.append(match.group(1))

    # 裸 JSON 数组：从每个 '[' 起尝试 raw_decode
    for match in re.finditer(r"\[\s*\{", stdout):
        chunk = stdout[match.start() :]
        parsed = _try_parse_subtasks_json(chunk)
        if parsed is not None:
            candidates.append(json.dumps(parsed, ensure_ascii=False))

    for raw in candidates:
        data = _try_parse_subtasks_json(raw)
        if data is not None:
            logger.debug("parse_manager_output: parsed %d subtasks", len(data))
            return data

    loose = _extract_subtask_objects(stdout)
    if loose is not None:
        logger.debug("parse_manager_output: found %d subtasks via loose extract", len(loose))
        return loose

    logger.warning("parse_manager_output failed: stdout[%d chars] start=[%.200s...]", len(stdout), stdout)
    if MARKER not in stdout:
        raise ValueError(f"missing marker {MARKER!r} in manager output")
    raise ValueError("found marker but no valid JSON subtasks array after it")


def validate_subtasks(
    subtasks: list[dict[str, Any]],
    project_dir: Path,
    manager_id: str,
) -> list[dict[str, Any]]:
    """校验 assignee 在主管子树内且字段完整。"""
    from core.org.tree_ops import OrgTree

    from core.org.persist import load_positions_data
    data = load_positions_data(project_dir)
    tree = OrgTree.from_yaml_data(data)
    allowed = set(tree.subtree(manager_id)) - {manager_id}
    if not subtasks:
        raise ValueError("subtasks list is empty")
    normalized: list[dict[str, Any]] = []
    for spec in subtasks:
        assignee = spec.get("assignee")
        if not assignee or assignee not in allowed:
            raise ValueError(f"invalid assignee {assignee!r}; allowed: {sorted(allowed)}")
        waits = spec.get("waits_on") or []
        if not isinstance(waits, list):
            raise ValueError("waits_on must be a list")
        normalized.append(
            {
                "assignee": assignee,
                "description": str(spec.get("description") or "").strip(),
                "waits_on": [str(w) for w in waits],
            }
        )
        if not normalized[-1]["description"]:
            raise ValueError(f"empty description for assignee {assignee}")
    return normalized


def load_decompose_result(project_dir: Path, manager_id: str) -> list[dict[str, Any]] | None:
    path = project_dir / "agents" / manager_id / "runtime" / "decompose_result.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_decompose_result(
    project_dir: Path, manager_id: str, subtasks: list[dict[str, Any]]
) -> Path:
    path = project_dir / "agents" / manager_id / "runtime" / "decompose_result.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(subtasks, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def generate_mock_subtasks(project_dir: Path, description: str) -> list[dict[str, Any]]:
    """无真实 Agent 时，根据 positions.yaml 生成默认子任务。"""
    from core.org.persist import load_positions_data
    data = load_positions_data(project_dir)
    positions = data.get("positions", [])
    manager_ids = {p["id"] for p in positions if p.get("is_manager")}
    workers = [p for p in positions if p.get("id") not in manager_ids and p.get("parent")]
    subtasks: list[dict[str, Any]] = []
    for w in workers:
        waits = w.get("waits_on") or []
        if isinstance(waits, list) and waits:
            waits_on = [x if isinstance(x, str) else x.get("id", x) for x in waits]
        else:
            waits_on = []
        subtasks.append(
            {
                "assignee": w["id"],
                "description": f"{description} — {w.get('title', w['id'])}",
                "waits_on": waits_on,
            }
        )
    return subtasks


def apply_subtasks(
    project_dir: Path,
    root_task_id: str,
    subtasks: list[dict[str, Any]],
    root_description: str,
    manager_id: str = "laowang",
) -> list[dict[str, Any]]:
    """写入子任务 YAML 并投递 inbox；返回已创建子任务列表。"""
    active = project_dir / "tasks" / "active"
    active.mkdir(parents=True, exist_ok=True)
    created: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc).isoformat()

    for spec in subtasks:
        assignee = spec["assignee"]
        waits_on = spec.get("waits_on") or []
        sub_id = f"{root_task_id}-{assignee}"
        status = "blocked" if waits_on else "assigned"
        task = {
            "id": sub_id,
            "parent_id": root_task_id,
            "description": spec.get("description", root_description),
            "status": status,
            "assignee": assignee,
            "waits_on": waits_on,
            "created_at": now,
            "updated_at": now,
        }
        (active / f"{sub_id}.yaml").write_text(
            yaml.dump(task, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        if status == "assigned":
            bus = MessageBus(project_dir / "agents" / assignee / "inbox")
            bus.deliver(
                Message(
                    id=Message.new_id(),
                    type="task_assign",
                    sender=manager_id,
                    recipient=assignee,
                    task_id=sub_id,
                    payload={"description": task["description"]},
                    trace=["ceo", manager_id],
                )
            )
        created.append(task)
    return created


def get_ready_subtasks(project_dir: Path) -> list[dict[str, Any]]:
    """返回 blocked 已解除、可开工的子任务。

    扫描 active + archive，确保归档依赖也能解除阻塞。
    """
    active = project_dir / "tasks" / "active"
    archive = project_dir / "tasks" / "archive"
    all_tasks: list[dict[str, Any]] = []
    for d in (active, archive):
        if d.is_dir():
            for path in d.glob("*.yaml"):
                try:
                    all_tasks.append(yaml.safe_load(path.read_text(encoding="utf-8")))
                except Exception:
                    continue
    done_ids = {
        t["assignee"]
        for t in all_tasks
        if t.get("status") in ("submitted", "approved", "archived")
    }
    ready: list[dict[str, Any]] = []
    for t in all_tasks:
        if t.get("status") != "blocked":
            continue
        waits = t.get("waits_on") or []
        if all(w in done_ids for w in waits):
            ready.append(t)
    return ready
