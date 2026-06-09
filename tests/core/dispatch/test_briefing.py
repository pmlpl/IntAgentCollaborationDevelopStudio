# tests/core/dispatch/test_briefing.py
from core.dispatch.briefing import (
    approve_brief,
    apply_answers_for_project,
    build_task_proposal,
    detail_brief_questions,
    generate_brief_questions,
    load_brief,
    mark_brief_dispatched,
    save_brief,
    start_brief_session,
    TaskBrief,
)
from core.project_profile import ProjectProfile


def test_generate_brief_questions_includes_defaults():
    qs = generate_brief_questions(None, "记账应用")
    assert len(qs) >= 4
    assert qs[0].id == "first_delivery"
    assert "记账" in qs[0].default


def test_detail_brief_questions_excludes_first_delivery():
    all_q = generate_brief_questions(None, "记账")
    detail = detail_brief_questions(None, "记账")
    assert len(detail) == len(all_q) - 1
    assert all(q.id != "first_delivery" for q in detail)


def test_build_task_proposal():
    brief = TaskBrief(
        project_description="记账应用",
        answers={
            "first_delivery": "登录与账单列表",
            "mvp_scope": "增删改查",
            "approach": "Vue3 + FastAPI",
            "acceptance": "可本地启动演示",
            "constraints": "不用付费服务",
        },
    )
    profile = ProjectProfile(
        description="记账应用",
        technologies_primary=["Vue3", "FastAPI"],
        domain="个人财务",
    )
    text = build_task_proposal(brief, profile)
    assert "登录与账单列表" in text
    assert "Vue3" in text
    assert "验收标准" in text


def test_brief_persistence(tmp_path):
    project_dir = tmp_path / "proj" / ".studio"
    project_dir.mkdir(parents=True)
    brief = start_brief_session(project_dir, "demo 项目")
    brief = apply_answers_for_project(
        project_dir,
        brief,
        {"first_delivery": "首页", "acceptance": "能跑通"},
    )
    assert brief.status == "pending_approval"
    assert brief.proposal

    loaded = load_brief(project_dir)
    assert loaded is not None
    assert loaded.answers["first_delivery"] == "首页"

    brief = approve_brief(project_dir, loaded)
    assert brief.status == "approved"
    assert brief.final_task

    brief = mark_brief_dispatched(project_dir, brief, "task-abc")
    assert brief.status == "dispatched"
    assert brief.task_id == "task-abc"

    again = load_brief(project_dir)
    assert again.status == "dispatched"


def test_start_brief_session_reuses_undispatched(tmp_path):
    project_dir = tmp_path / "p" / ".studio"
    project_dir.mkdir(parents=True)
    b1 = start_brief_session(project_dir, "A")
    b1.answers = {"first_delivery": "x"}
    save_brief(project_dir, b1)
    b2 = start_brief_session(project_dir, "B")
    assert b2.answers.get("first_delivery") == "x"


def test_start_brief_session_new_cycle_after_dispatched(tmp_path):
    project_dir = tmp_path / "p" / ".studio"
    project_dir.mkdir(parents=True)
    b1 = start_brief_session(project_dir, "A")
    b1.status = "dispatched"
    save_brief(project_dir, b1)
    b2 = start_brief_session(project_dir, "新任务")
    assert b2.status == "collecting"
    assert b2.answers == {}
