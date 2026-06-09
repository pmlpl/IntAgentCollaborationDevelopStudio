# core/research/expand.py — 扩建调研（复用 research_project）
from __future__ import annotations

from pathlib import Path

from core.research.research import research_project


def expand_research(
    description: str,
    root: Path | None = None,
    *,
    project_dir: Path | None = None,
) -> dict[str, str | list[str]]:
    """根据新业务描述推荐模板与需新增岗位（读/写 PROJECT.md）。"""
    base = research_project(description, root, project_dir=project_dir)
    template_id = str(base["recommended_template"])
    role_map: dict[str, list[str]] = {
        "web-miniprogram": ["xiaocheng"],
        "web-mobile": ["xiaomo"],
        "multi-endpoint": ["xiaomo", "xiaocheng", "xiaozhuo"],
        "web-fullstack": [],
    }
    suggested_roles = role_map.get(template_id, [])
    extra_note = ""
    if suggested_roles:
        extra_note = f"\n建议新增岗位：{', '.join(suggested_roles)}"
    elif template_id == "web-fullstack":
        extra_note = "\n当前团队已覆盖 Web 全栈，可考虑部门内加人或加管理层。"

    return {
        "summary": str(base["summary"]) + extra_note,
        "recommended_template": template_id,
        "suggested_roles": suggested_roles,
        "source": str(base.get("source", "mock")),
    }


def mock_expand_research(description: str, project_dir: Path | None = None) -> dict[str, str | list[str]]:
    """兼容旧调用名。"""
    from core.project import get_studio_root

    return expand_research(description, get_studio_root(), project_dir=project_dir)
