# core/research/research.py — 统一调研入口：读 PROJECT.md → 调研 Agent → 写回
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from core.research.agent_research import report_to_result_dict, run_agent_research


def research_project(
    description: str,
    root: Path | None = None,
    *,
    project_dir: Path | None = None,
    tech_stack: str = "",
    force_web: bool = False,
    allow_template_reuse: bool = True,
) -> dict[str, Any]:
    """项目调研：先读 PROJECT.md，再联网 + Agent 分析，有 project_dir 时写回画像。"""
    _ = allow_template_reuse
    force_offline = force_web is False and os.environ.get("STUDIO_RESEARCH_OFFLINE", "").lower() in (
        "1",
        "true",
        "yes",
    )
    report = run_agent_research(
        description,
        root,
        project_dir=project_dir,
        tech_stack=tech_stack,
        force_offline=force_offline,
    )
    result = report_to_result_dict(report)
    result["profile_updated"] = project_dir is not None
    return result
