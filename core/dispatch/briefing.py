# core/dispatch/briefing.py — CEO 任务澄清：提问、方案、审批持久化
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from core.project_profile import ProjectProfile, load_profile

BRIEF_FILENAME = "ceo_brief.yaml"


@dataclass
class BriefQuestion:
    """单条澄清问题。"""

    id: str
    prompt: str
    placeholder: str = ""
    default: str = ""
    required: bool = True
    multiline: bool = False


@dataclass
class TaskBrief:
    """CEO 任务澄清会话状态。"""

    project_description: str = ""
    status: str = "collecting"  # collecting | pending_approval | approved | dispatched
    answers: dict[str, str] = field(default_factory=dict)
    proposal: str = ""
    final_task: str = ""
    task_id: str | None = None
    created_at: str = ""
    approved_at: str = ""
    updated_at: str = ""


def brief_path(project_dir: Path) -> Path:
    """澄清文件路径（位于 .studio/ceo_brief.yaml）。"""
    return project_dir / BRIEF_FILENAME


def load_brief(project_dir: Path) -> TaskBrief | None:
    """读取已保存的澄清会话。"""
    path = brief_path(project_dir)
    if not path.is_file():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return None
    return TaskBrief(
        project_description=str(data.get("project_description") or ""),
        status=str(data.get("status") or "collecting"),
        answers={str(k): str(v) for k, v in (data.get("answers") or {}).items()},
        proposal=str(data.get("proposal") or ""),
        final_task=str(data.get("final_task") or ""),
        task_id=data.get("task_id"),
        created_at=str(data.get("created_at") or ""),
        approved_at=str(data.get("approved_at") or ""),
        updated_at=str(data.get("updated_at") or ""),
    )


def save_brief(project_dir: Path, brief: TaskBrief) -> Path:
    """持久化澄清会话。"""
    now = datetime.now(timezone.utc).isoformat()
    if not brief.created_at:
        brief.created_at = now
    brief.updated_at = now
    path = brief_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "project_description": brief.project_description,
        "status": brief.status,
        "answers": brief.answers,
        "proposal": brief.proposal,
        "final_task": brief.final_task,
        "task_id": brief.task_id,
        "created_at": brief.created_at,
        "approved_at": brief.approved_at,
        "updated_at": brief.updated_at,
    }
    path.write_text(yaml.dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def generate_brief_questions(
    profile: ProjectProfile | None,
    project_description: str,
) -> list[BriefQuestion]:
    """根据项目画像生成澄清问题列表。"""
    tech_hint = ""
    if profile and profile.technologies_primary:
        tech_hint = f"（调研推荐：{', '.join(profile.technologies_primary[:5])}）"

    default_first = (project_description or "").strip()
    if profile and profile.description:
        default_first = profile.description.strip()

    questions: list[BriefQuestion] = [
        BriefQuestion(
            id="first_delivery",
            prompt="第一个要交付的功能/里程碑是什么？",
            placeholder="例如：用户注册登录 + 首页列表",
            default=default_first[:300],
            required=True,
        ),
        BriefQuestion(
            id="mvp_scope",
            prompt="首批 MVP 还应包含哪些能力？",
            placeholder="例如：CRUD、搜索、权限、导出…",
            multiline=True,
        ),
        BriefQuestion(
            id="approach",
            prompt="你倾向于怎么做？实现路径或技术偏好",
            placeholder=f"例如：先做静态页再联调 API；或指定框架 {tech_hint}".strip(),
            multiline=True,
        ),
        BriefQuestion(
            id="acceptance",
            prompt="怎样算做完？验收标准是什么？",
            placeholder="例如：核心流程可跑通、有基础测试、README 可启动",
            required=True,
        ),
        BriefQuestion(
            id="constraints",
            prompt="有没有必须遵守或禁止的约束？",
            placeholder="例如：必须用 Vue3、不能引入付费 SaaS、本周内可演示",
            multiline=True,
        ),
    ]
    return questions


def build_task_proposal(
    brief: TaskBrief,
    profile: ProjectProfile | None = None,
) -> str:
    """把澄清答案合成为给 CEO 审阅、主管拆解用的任务方案。"""
    answers = brief.answers
    lines = [
        "【CEO 已确认任务方案】",
        "",
        f"项目概述：{brief.project_description or '（未填）'}",
        "",
        f"首交付目标：{answers.get('first_delivery', '').strip() or '（未填）'}",
        "",
        f"MVP 范围：{answers.get('mvp_scope', '').strip() or '（按首交付目标展开）'}",
        "",
        f"实现路径：{answers.get('approach', '').strip() or '（由主管与团队自行选型）'}",
        "",
        f"验收标准：{answers.get('acceptance', '').strip() or '（未填）'}",
    ]
    constraint = answers.get("constraints", "").strip()
    if constraint:
        lines.extend(["", f"约束条件：{constraint}"])

    if profile:
        if profile.technologies_primary:
            lines.extend(["", f"调研主选技术栈：{', '.join(profile.technologies_primary)}"])
        if profile.domain:
            lines.extend(["", f"业务域：{profile.domain}"])
        if profile.research_summary:
            summary = profile.research_summary.replace("\n", " ").strip()[:400]
            lines.extend(["", f"调研摘要：{summary}"])

    lines.extend(
        [
            "",
            "请主管据此拆解子任务，分配给团队成员，并在 description 中写明各岗位应使用的 skills。",
        ]
    )
    return "\n".join(lines)


def start_brief_session(project_dir: Path, project_description: str) -> TaskBrief:
    """新建或恢复澄清会话；已 dispatched 的任务开始新一轮收集。"""
    existing = load_brief(project_dir)
    if existing and existing.status == "dispatched":
        brief = TaskBrief(
            project_description=project_description.strip(),
            status="collecting",
        )
        save_brief(project_dir, brief)
        return brief
    if existing and existing.status != "dispatched":
        if project_description.strip() and not existing.project_description:
            existing.project_description = project_description.strip()
        return existing
    brief = TaskBrief(
        project_description=project_description.strip(),
        status="collecting",
    )
    save_brief(project_dir, brief)
    return brief


def detail_brief_questions(
    profile: ProjectProfile | None,
    project_description: str,
) -> list[BriefQuestion]:
    """澄清细节题（不含首交付，首交付在「下达任务」第一步单独填写）。"""
    return [q for q in generate_brief_questions(profile, project_description) if q.id != "first_delivery"]


def render_dispatch_compact_line(profile: ProjectProfile | None, description: str) -> str:
    """下达任务弹窗用的一行项目摘要（省垂直空间）。"""
    desc = (description or "").strip()
    if profile and profile.description:
        desc = profile.description.strip()
    label = (desc[:36] + "…") if len(desc) > 36 else (desc or "未命名项目")
    extras: list[str] = []
    if profile and profile.org_template:
        extras.append(f"模板 {profile.org_template}")
    if profile and profile.domain:
        extras.append(profile.domain)
    tail = f" · {' · '.join(extras)}" if extras else ""
    return f"[dim]项目：[/]{label}{tail}"


def render_dispatch_intro(profile: ProjectProfile | None, description: str) -> str:
    """下达任务第一步：项目概况。"""
    text = render_profile_summary(profile, description)
    return text.replace(
        "接下来会逐项问你：首交付、MVP、做法、验收与约束。",
        "先填写本次业务目标（主管负责拆解与验收细节）。",
    )


def apply_answers_for_project(project_dir: Path, brief: TaskBrief, answers: dict[str, str]) -> TaskBrief:
    """写入答案、生成 CEO→主管 方案并保存。"""
    from core.dispatch.delivery import build_ceo_dispatch_brief

    brief.answers = {k: v.strip() for k, v in answers.items()}
    goal = brief.answers.get("first_delivery", brief.project_description)
    notes = brief.answers.get("ceo_notes", "")
    brief.proposal = build_ceo_dispatch_brief(goal, notes)
    brief.status = "pending_approval"
    save_brief(project_dir, brief)
    return brief


def approve_brief(project_dir: Path, brief: TaskBrief, *, final_task: str | None = None) -> TaskBrief:
    """CEO 批准方案，准备下发主管。"""
    brief.final_task = (final_task or brief.proposal).strip()
    brief.status = "approved"
    brief.approved_at = datetime.now(timezone.utc).isoformat()
    save_brief(project_dir, brief)
    return brief


def mark_brief_dispatched(project_dir: Path, brief: TaskBrief, task_id: str) -> TaskBrief:
    """编排已启动，记录根任务 id。"""
    brief.status = "dispatched"
    brief.task_id = task_id
    save_brief(project_dir, brief)
    return brief


def ceo_context_for_workers(project_dir: Path) -> str:
    """供 Worker Agent 注入的 CEO 已确认总目标文本。"""
    brief = load_brief(project_dir)
    if not brief:
        return ""
    if brief.final_task.strip():
        return brief.final_task.strip()
    if brief.proposal.strip():
        return brief.proposal.strip()
    return brief.project_description.strip()


def render_profile_summary(profile: ProjectProfile | None, description: str) -> str:
    """TUI 展示用的项目概况文本。"""
    lines = ["[bold cyan]项目概况[/]", ""]
    desc = description
    if profile and profile.description:
        desc = profile.description
    lines.append(desc or "（暂无描述）")
    if profile and profile.has_substance:
        if profile.technologies_primary:
            lines.append("")
            lines.append(f"[dim]技术栈：[/]{', '.join(profile.technologies_primary)}")
        if profile.domain:
            lines.append(f"[dim]业务域：[/]{profile.domain}")
        if profile.org_template:
            lines.append(f"[dim]组织模板：[/]{profile.org_template}")
    lines.extend(["", "[dim]接下来会逐项问你：首交付、MVP、做法、验收与约束。[/]"])
    return "\n".join(lines)


def render_proposal_panel(brief: TaskBrief) -> str:
    """TUI 展示待审批方案。"""
    body = brief.proposal or "（方案为空）"
    return (
        "[bold magenta]▸ 待你审批的任务方案[/]\n\n"
        f"{body}\n\n"
        "[dim]确认后将交给主管拆解并打开各 Agent 终端。[/]"
    )
