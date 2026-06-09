# cli/tui/screens/briefing.py — 统一下达任务：CEO 目标 → 审批
from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static, TextArea

from core.dispatch.briefing import (
    approve_brief,
    apply_answers_for_project,
    render_dispatch_intro,
    render_proposal_panel,
    start_brief_session,
)
from core.project import get_studio_root, load_project
from core.project_profile import load_profile


class TaskDispatchScreen(ModalScreen[str | None]):
    """CEO 下达业务目标；技术拆解与验收由主管负责。"""

    DEFAULT_CSS = """
    TaskDispatchScreen {
        align: center middle;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "取消"),
        ("ctrl+enter", "next_step", "继续"),
    ]

    def __init__(self, project_name: str, *, is_new: bool = False) -> None:
        super().__init__()
        self.project_name = project_name
        self.is_new = is_new
        self._step = 0
        self._answers: dict[str, str] = {}
        self._brief = None
        self._profile = None
        self._project_dir: Path | None = None

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("[bold]下达任务（CEO）[/]", classes="title-text"),
            Static("", id="dispatch-step-indicator", classes="muted"),
            Vertical(
                VerticalScroll(
                    Static("", id="dispatch-overview", classes="panel-box"),
                    id="dispatch-overview-scroll",
                ),
                Static("本次要做什么 [red]*[/]", classes="accent"),
                Input(placeholder="例如：做一个可玩的贪吃蛇小游戏", id="dispatch-goal-input"),
                Static("可选补充（约束、偏好、截止时间等）", classes="muted"),
                TextArea("", id="dispatch-notes-input", show_line_numbers=False),
                Static("", id="dispatch-goal-hint", classes="muted"),
                Horizontal(
                    Button("取消", id="btn-dispatch-cancel"),
                    Button("生成方案", variant="primary", id="btn-dispatch-start"),
                ),
                id="dispatch-step-goal",
            ),
            Vertical(
                VerticalScroll(
                    Static("", id="dispatch-proposal", classes="panel-box"),
                    id="dispatch-proposal-scroll",
                ),
                Static(
                    "[dim]确认后交给主管老王拆解子任务、补充 MVP 与验收标准，并打开各 Agent 终端。[/]",
                    classes="muted",
                ),
                Horizontal(
                    Button("返回修改", id="btn-dispatch-revise"),
                    Button("批准并下达", variant="success", id="btn-dispatch-approve"),
                ),
                Static("", id="dispatch-error", classes="muted"),
                id="dispatch-step-approve",
            ),
            id="dispatch-container",
            classes="panel-box",
        )

    def on_mount(self) -> None:
        root = get_studio_root()
        self._project_dir = load_project(root, self.project_name)
        self._profile = load_profile(self._project_dir)
        desc = (self._profile.description if self._profile else "") or ""
        positions = self._project_dir / "positions.yaml"
        if positions.is_file():
            import yaml

            data = yaml.safe_load(positions.read_text(encoding="utf-8")) or {}
            desc = str(data.get("description") or desc)

        self._brief = start_brief_session(self._project_dir, desc)
        self._answers = dict(self._brief.answers)

        overview = render_dispatch_intro(self._profile, desc)
        if self.is_new:
            overview = "[green]项目已创建。[/]\n\n" + overview
        self.query_one("#dispatch-overview", Static).update(overview)

        goal = self._answers.get("first_delivery", "")
        if not goal and desc:
            goal = desc[:300]
        self.query_one("#dispatch-goal-input", Input).value = goal
        self.query_one("#dispatch-notes-input", TextArea).text = self._answers.get(
            "ceo_notes", ""
        )
        self.query_one("#dispatch-goal-input", Input).focus()

        if self._brief.status == "pending_approval" and self._brief.proposal:
            self._show_step(1)
        else:
            self._show_step(0)

    def _show_step(self, step: int) -> None:
        self._step = step
        label = "1/2 业务目标" if step == 0 else "2/2 审批"
        self.query_one("#dispatch-step-indicator", Static).update(f"步骤 · {label}")
        self.query_one("#dispatch-step-goal").display = step == 0
        self.query_one("#dispatch-step-approve").display = step == 1
        if step == 1:
            self._render_proposal()

    def _save_goal_step(self) -> str | None:
        goal = self.query_one("#dispatch-goal-input", Input).value.strip()
        if not goal:
            return "请填写本次要做什么"
        notes = self.query_one("#dispatch-notes-input", TextArea).text.strip()
        self._answers["first_delivery"] = goal
        self._answers["ceo_notes"] = notes
        return None

    def _render_proposal(self) -> None:
        assert self._project_dir and self._brief
        self._brief = apply_answers_for_project(self._project_dir, self._brief, self._answers)
        self.query_one("#dispatch-proposal", Static).update(render_proposal_panel(self._brief))
        self.query_one("#dispatch-error", Static).update("")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "btn-dispatch-cancel":
            self.action_cancel()
        elif bid == "btn-dispatch-start":
            self.action_next_step()
        elif bid == "btn-dispatch-revise":
            self._show_step(0)
        elif bid == "btn-dispatch-approve":
            self._approve_and_dispatch()

    def action_next_step(self) -> None:
        if self._step == 0:
            err = self._save_goal_step()
            if err:
                self.query_one("#dispatch-goal-hint", Static).update(f"[red]{err}[/]")
                return
            self.query_one("#dispatch-goal-hint", Static).update("")
            self._show_step(1)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _approve_and_dispatch(self) -> None:
        assert self._project_dir and self._brief
        if not self._brief.proposal.strip():
            self.query_one("#dispatch-error", Static).update("[red]方案为空，请返回修改[/]")
            return
        self._brief = approve_brief(self._project_dir, self._brief)
        self.app.project_name = self.project_name
        self.dismiss(self._brief.final_task)


BriefingScreen = TaskDispatchScreen
