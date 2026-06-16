from pathlib import Path

import yaml

from agents.interactive import format_worker_task_prompt, write_task_context_file
from core.dispatch.briefing import approve_brief, apply_answers_for_project, start_brief_session


def test_format_worker_task_prompt_includes_ceo_brief(tmp_path: Path):
    project_dir = tmp_path / ".studio"
    project_dir.mkdir(parents=True)
    brief = start_brief_session(project_dir, "记账应用")
    brief = apply_answers_for_project(
        project_dir,
        brief,
        {"first_delivery": "登录页", "acceptance": "可演示"},
    )
    approve_brief(project_dir, brief)

    text = format_worker_task_prompt(
        project_dir,
        "实现前端登录表单",
        task_id="task-1-xiaohong",
        role="小红 (前端)",
    )
    assert "CEO Confirmed Goal" in text
    assert "登录页" in text
    assert "Your Sub-task" in text
    assert "实现前端登录表单" in text

    wt = tmp_path / "wt"
    wt.mkdir()
    rel = write_task_context_file(wt, text)
    saved = (wt / rel).read_text(encoding="utf-8")
    assert "实现前端登录表单" in saved
