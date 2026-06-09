# core/dispatch/review_compliance.py — 防线三：审查技能合规检查
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from core.org.tree_ops import OrgTree
from core.platform.skills_client import load_skills_registry
from core.rbac.permission import effective_skill_use


def extract_required_skills(description: str) -> list[str]:
    """从任务描述中提取点名的 skill id（skills= / skill: 形式）。"""
    found: set[str] = set()
    for match in re.finditer(r"skills?\s*[=:]\s*[\[\(]?([\w\-,\s]+)", description, re.I):
        chunk = match.group(1)
        for part in re.split(r"[,，\s]+", chunk):
            part = part.strip("[]()")
            if part and re.match(r"^[\w\-]+$", part):
                found.add(part)
    for match in re.finditer(r"`([\w\-]+)`", description):
        token = match.group(1)
        if "-" in token:
            found.add(token)
    return sorted(found)


def build_review_checklist(
    root: Any,
    tree: OrgTree,
    task: dict[str, Any],
    assignee: dict[str, Any],
) -> list[str]:
    """生成审查清单条目（含技能合规）。"""
    registry = set(load_skills_registry(root))
    allowed = effective_skill_use(tree, assignee, registry)
    desc = task.get("description") or ""
    required = extract_required_skills(desc)
    lines = [
        "□ 代码是否满足任务描述的功能要求",
        "□ 是否引入未审批的新依赖",
        "□ 安全与权限相关改动是否已标注",
    ]
    if required:
        for sid in required:
            if sid in registry:
                ok = sid in allowed
                mark = "✓" if ok else "✗"
                lines.append(f"□ 技能合规 [{mark}] 任务要求 `{sid}`，执行者可用: {sorted(allowed)}")
            else:
                lines.append(f"□ 技能合规 [?] 任务引用了未注册技能 `{sid}`")
    elif assignee.get("resume", {}).get("skills"):
        skills = assignee["resume"]["skills"]
        lines.append(f"□ 审查是否遵循岗位默认技能: {skills}")
    return lines


def format_review_checklist(lines: list[str]) -> str:
    return "\n".join(lines)


def compliance_for_task(
    root: Path,
    project_dir: Path,
    task_id: str,
) -> str:
    """为一个待审查任务生成合规检查清单文本，供注入 review prompt。"""
    task_path = project_dir / "tasks" / "active" / f"{task_id}.yaml"
    if not task_path.exists():
        return "（无合规检查项 — 任务文件丢失）"

    pos_path = project_dir / "positions.yaml"
    if not pos_path.exists():
        return "（无合规检查项 — 组织文件丢失）"

    task = yaml.safe_load(task_path.read_text(encoding="utf-8"))
    data = yaml.safe_load(pos_path.read_text(encoding="utf-8"))
    tree = OrgTree.from_yaml_data(data)
    assignee = next(
        (p for p in data.get("positions", []) if p["id"] == task.get("assignee")),
        {"id": task.get("assignee", ""), "resume": {}},
    )
    lines = build_review_checklist(root, tree, task, assignee)
    return format_review_checklist(lines)
