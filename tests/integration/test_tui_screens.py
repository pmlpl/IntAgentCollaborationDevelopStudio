# tests/integration/test_tui_screens.py — TUI 真挂载测试（Textual Pilot，非 import smoke）
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from textual.app import App
from textual.widgets import Select

from cli.tui.screens.briefing import TaskDispatchScreen
from cli.tui.screens.expand import ExpandScreen
from cli.tui.screens.onboarding import OnboardingScreen
from cli.tui.screens.position_editor import PositionEditorModal
from cli.tui.screens.project_hub import ProjectHubScreen
from core.config.select_helpers import safe_select_value
from core.project import (
    ORG_TEMPLATES,
    build_positions_data,
    init_project,
    list_registered_projects,
)


def _studio_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project_id: str = "demo") -> str:
    """在 tmp_path 初始化最小 Studio 根目录与一个项目。"""
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "agents.yaml").write_text("agents: {}\n", encoding="utf-8")
    (tmp_path / "config" / "models.yaml").write_text("models: {}\n", encoding="utf-8")
    init_project(
        tmp_path,
        project_id,
        project_path=tmp_path / "projects" / project_id,
        description="测试项目",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("core.project.get_studio_root", lambda: tmp_path)
    return project_id


async def _run_with_screen(screen, *, size=(100, 40)):
    """挂载单个 Screen/Modal，返回 (app, pilot, screen)。"""
    app = App()
    pilot_cm = app.run_test(size=size)
    pilot = await pilot_cm.__aenter__()
    await app.push_screen(screen)
    await pilot.pause()
    return app, pilot, pilot_cm


async def _cleanup(pilot_cm, pilot):
    await pilot_cm.__aexit__(None, None, None)


def test_onboarding_mounts_and_sets_org_template():
    """回归：新建项目 on_mount → _reset_wizard → safe_select_value 不能炸。"""

    async def _case():
        app, pilot, cm = await _run_with_screen(OnboardingScreen())
        try:
            tpl = app.screen.query_one("#org-template", Select)
            assert tpl.value == "web-fullstack"
            safe_select_value(tpl, "minimal", fallback="web-fullstack")
            assert tpl.value == "minimal"
        finally:
            await _cleanup(cm, pilot)

    asyncio.run(_case())


def test_onboarding_step2_shows_research_roles_hint():
    async def _case():
        app, pilot, cm = await _run_with_screen(OnboardingScreen())
        try:
            screen = app.screen
            screen._research_text = "调研完成"
            screen._recommended_roles = {"laowang", "dazhuang", "xiaoyan"}
            screen._template_id = "minimal"
            screen._show_step(2)
            await pilot.pause()
            await pilot.pause()
            hint = screen.query_one("#research-roles-hint")
            assert "调研推荐" in str(hint.render())
            checkboxes = list(screen.query("#role-checkboxes Checkbox"))
            assert checkboxes, "岗位勾选列表应已渲染"
            assert any(cb.value for cb in checkboxes), "调研推荐岗位应至少勾选一个"
        finally:
            await _cleanup(cm, pilot)

    asyncio.run(_case())


def test_onboarding_edit_positions_opens_modal_with_valid_agent():
    """回归：按 E 逐岗配置，Agent Select 能设为 opencode。"""

    async def _case():
        app, pilot, cm = await _run_with_screen(OnboardingScreen())
        try:
            screen = app.screen
            screen._research_text = "done"
            screen._recommended_roles = set(ORG_TEMPLATES["web-fullstack"]["roles"])
            screen._template_id = "web-fullstack"
            screen._show_step(2)
            await pilot.pause()
            await pilot.press("e")
            await pilot.pause()
            assert type(app.screen).__name__ == "PositionEditorModal"
            agent_sel = app.screen.query_one("#agent-select", Select)
            assert agent_sel.value == "opencode"
            safe_select_value(agent_sel, "hermes", fallback="opencode")
            assert agent_sel.value == "hermes"
        finally:
            await _cleanup(cm, pilot)

    asyncio.run(_case())


def test_position_editor_cycles_positions_without_error():
    async def _case():
        positions = build_positions_data("demo", "测试", "web-fullstack")["positions"]
        app, pilot, cm = await _run_with_screen(PositionEditorModal(positions))
        try:
            modal = app.screen
            modal._load_position(1)
            await pilot.pause()
            agent_sel = modal.query_one("#agent-select", Select)
            assert agent_sel.value in {"opencode", "hermes", "aider"}
            parent_sel = modal.query_one("#parent-select", Select)
            assert parent_sel.value is not None
        finally:
            await _cleanup(cm, pilot)

    asyncio.run(_case())


def test_task_dispatch_mounts_with_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _studio_tmp(tmp_path, monkeypatch, "snake")

    async def _case():
        app, pilot, cm = await _run_with_screen(TaskDispatchScreen("snake"))
        try:
            assert app.screen.query_one("#dispatch-goal-input") is not None
            assert app.screen.query_one("#btn-dispatch-start") is not None
        finally:
            await _cleanup(cm, pilot)

    asyncio.run(_case())


def test_expand_screen_mounts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pid = _studio_tmp(tmp_path, monkeypatch, "expandme")

    async def _case():
        app, pilot, cm = await _run_with_screen(ExpandScreen(pid))
        try:
            assert app.screen.query_one("#expand-mode", Select) is not None
            assert app.screen.query_one("#btn-primary") is not None
        finally:
            await _cleanup(cm, pilot)

    asyncio.run(_case())


def test_project_hub_lists_registered_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _studio_tmp(tmp_path, monkeypatch, "hubtest")
    assert len(list_registered_projects(tmp_path)) == 1

    async def _case():
        app, pilot, cm = await _run_with_screen(ProjectHubScreen())
        try:
            await pilot.pause()
            screen = app.screen
            assert len(screen._projects) == 1
            assert screen._projects[0]["id"] == "hubtest"
        finally:
            await _cleanup(cm, pilot)

    asyncio.run(_case())


def test_project_hub_delete_removes_from_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """回归：Del 删除后列表与 registry 均应清空。"""
    _studio_tmp(tmp_path, monkeypatch, "todelete")

    async def _case():
        app, pilot, cm = await _run_with_screen(ProjectHubScreen())
        try:
            await pilot.pause()
            screen = app.screen
            assert len(screen._projects) == 1
            screen.action_delete_selected()
            await pilot.pause()
            await pilot.click("#confirm")
            await pilot.pause()
            await pilot.pause()
            assert len(screen._projects) == 0
            assert list_registered_projects(tmp_path) == []
        finally:
            await _cleanup(cm, pilot)

    asyncio.run(_case())
