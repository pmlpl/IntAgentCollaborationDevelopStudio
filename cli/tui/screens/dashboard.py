# cli/tui/screens/dashboard.py — CEO 指挥舱
from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, ProgressBar, Static

from cli.tui.screens.briefing import TaskDispatchScreen
from cli.tui.screens.expand import ExpandScreen
from cli.tui.screens.onboarding import OnboardingScreen
from cli.tui.widgets.org_tree import render_org_tree
from cli.tui.widgets.orchestration_panel import render_orchestration_panel
from cli.tui.widgets.task_panel import render_task_panel
from core.config.agent_policy import agent_enabled
from core.dispatch.briefing import load_brief, mark_brief_dispatched
from core.dispatch.dispatcher import get_dispatcher
from core.dispatch.orchestration_progress import compute_orchestration_progress
from core.project import (
    clear_stale_current_project,
    get_project_root,
    get_studio_root,
    load_project,
    project_exists,
    resolve_project_id,
    set_current_project,
)
from core.supervisor_client import SupervisorClient


class DashboardScreen(Screen):
    """指挥舱主界面。"""

    BINDINGS = [
        ("n", "dispatch_task", "下达任务"),
        ("e", "expand", "扩建"),
        ("s", "refresh", "刷新"),
        ("r", "review", "审批"),
        ("p", "projects", "项目中心"),
        ("a", "agents", "Agent 目录"),
        ("shift+n", "new_project", "新建项目"),
        ("q", "quit", "退出"),
    ]

    def __init__(self, project_name: str | None = None) -> None:
        super().__init__()
        self.project_name = project_name
        self._pending_task_id: str | None = None
        self._pending_description: str = ""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Vertical(
            Static("", id="orch-panel-text"),
            ProgressBar(total=100, show_eta=False, id="orch-progress"),
            id="orch-container",
            classes="panel-box",
        )
        yield Horizontal(
            Static("", id="org-panel", classes="panel-box"),
            Static("", id="task-panel", classes="panel-box"),
            id="main-panels",
        )
        yield Footer()
        yield Static("", id="status-line", classes="muted")

    def on_mount(self) -> None:
        if not self.project_name and getattr(self.app, "project_name", None):
            self.project_name = self.app.project_name
        self.query_one("#orch-container").display = False
        self.set_interval(1, self._refresh)
        self._refresh()
        pending = getattr(self.app, "pending_orchestration", None)
        if pending:
            self.app.pending_orchestration = None
            if self._sync_project_name():
                self._start_orchestration(pending)
        elif getattr(self.app, "auto_open_task_dispatch", False):
            self.app.auto_open_task_dispatch = False
            self.action_dispatch_task()

    def on_screen_resume(self) -> None:
        """从项目中心返回时重新校验当前项目（可能已被删除）。"""
        self._refresh()

    def _sync_project_name(self) -> bool:
        """同步并校验当前项目；失效则清空缓存指针。"""
        root = get_studio_root()
        candidate = self.project_name or getattr(self.app, "project_name", None)
        if candidate and not project_exists(root, candidate):
            clear_stale_current_project(root, candidate)
            candidate = None
        if not candidate:
            try:
                candidate = resolve_project_id(root)
            except FileNotFoundError:
                self.project_name = None
                self.app.project_name = None
                return False
        self.project_name = candidate
        self.app.project_name = candidate
        set_current_project(root, candidate)
        return True

    def _show_no_project(self) -> None:
        """当前项目不存在时清空指挥舱面板。"""
        self.project_name = None
        self.app.project_name = None
        self._pending_task_id = None
        self._pending_description = ""
        self.query_one("#org-panel", Static).update("[dim]（无项目）[/]")
        self.query_one("#task-panel", Static).update(
            "[dim]当前项目已删除或不可用。[/]\n按 [bold]P[/] 打开项目中心选择或新建项目。"
        )
        self.query_one("#orch-container").display = False
        self.query_one("#status-line", Static).update(
            "[red]当前项目已不存在，按 P 打开项目中心[/]"
        )

    def _ensure_project(self) -> bool:
        if self._sync_project_name():
            return True
        self._show_no_project()
        return False

    def _start_orchestration(self, description: str) -> None:
        """创建根任务并启动主管拆解编排。"""
        root = get_studio_root()
        try:
            if not self._ensure_project():
                self.notify("请先选择或创建项目", severity="warning")
                return
            self.notify(
                f"正在下达：{description[:40]}…",
                title="任务下达",
                severity="information",
            )
            SupervisorClient(root).ensure_running()
            disp = get_dispatcher(root, self.project_name)
            task = disp.begin_orchestration(
                root, description, spawn_terminals=True, mock=False
            )
            self._pending_task_id = task["id"]
            self._pending_description = description
            brief = load_brief(disp.project_dir)
            if brief and brief.status == "approved":
                mark_brief_dispatched(disp.project_dir, brief, task["id"])
            self._refresh()
        except Exception as exc:
            self.notify(str(exc), title="下达失败", severity="error")
            self.query_one("#status-line", Static).update(f"[red]下达失败: {exc}[/]")

    def _update_orchestration_ui(self, disp, root: Path) -> None:
        """刷新编排进度条。"""
        if not self._pending_task_id:
            self.query_one("#orch-container").display = False
            return

        disp.try_complete_orchestration(root, self._pending_task_id, spawn_terminals=True)

        project_dir = disp.project_dir
        prog = compute_orchestration_progress(
            project_dir,
            self._pending_task_id,
            description=self._pending_description,
            tasks=disp.get_status(),
            states=disp.get_agent_states(),
        )
        self.query_one("#orch-container").display = True
        self.query_one("#orch-panel-text", Static).update(render_orchestration_panel(prog))
        bar = self.query_one("#orch-progress", ProgressBar)
        bar.progress = prog.percent
        color = "red" if prog.failed else "green" if prog.done else "yellow"
        self.query_one("#status-line", Static).update(
            f"[{color}]编排 {prog.percent}% — {prog.message}[/]"
        )

        if prog.done:
            self.notify(
                "编排完成：各 Worker 应已弹出交互式 Agent 终端",
                title="任务下达",
                severity="information",
            )
            self._pending_task_id = None
            self._pending_description = ""
        elif prog.failed:
            self.notify(prog.message, title="编排失败", severity="error")
            self._pending_task_id = None

    def _refresh(self) -> None:
        root = get_studio_root()
        if not self._sync_project_name():
            self._show_no_project()
            return

        try:
            load_project(root, self.project_name)
            project_root = get_project_root(root, self.project_name)
        except FileNotFoundError:
            self._show_no_project()
            return

        disp = get_dispatcher(root, self.project_name)
        disp.poll_deliveries(root)
        positions = disp.list_positions()
        tasks = disp.get_status()
        states = disp.get_agent_states()

        self.query_one("#org-panel", Static).update(render_org_tree(positions))
        self.query_one("#task-panel", Static).update(
            render_task_panel(
                tasks,
                positions,
                states,
                highlight_task_id=self._pending_task_id,
            )
        )

        if self._pending_task_id:
            self._update_orchestration_ui(disp, root)
            return

        self.query_one("#orch-container").display = False
        sup = "Supervisor ✓" if SupervisorClient(root).health() else "Supervisor …"
        mgr_pending = len(disp.get_manager_reviews())
        ceo_pending = len(disp.get_pending_reviews())

        # Agent 启用状态摘要
        agent_status = _build_agent_status(root, positions)

        extra = ""
        if mgr_pending:
            extra += f" · 主管审查中 {mgr_pending}"
        if ceo_pending:
            extra += f" · CEO 待批 {ceo_pending} (R)"
        status = (
            f"项目: {self.project_name} · {project_root} · {sup}{agent_status} · N 下达任务{extra}"
        )
        self.query_one("#status-line", Static).update(status)

    def action_refresh(self) -> None:
        self._refresh()

    def action_dispatch_task(self) -> None:
        """统一下达任务：CEO 填写业务目标 → 审批。"""

        def on_done(final_task: str | None) -> None:
            if final_task:
                self._start_orchestration(final_task)

        if not self._ensure_project():
            self.notify("请先选择或创建项目", severity="warning")
            return
        self.app.push_screen(
            TaskDispatchScreen(project_name=self.project_name, is_new=False),
            on_done,
        )

    def action_review(self) -> None:
        if not self._ensure_project():
            self.notify("请先选择或创建项目", severity="warning")
            return
        self.app.push_screen("review")

    def action_projects(self) -> None:
        self.app.switch_screen("project_hub")

    def action_agents(self) -> None:
        self.app.push_screen("agent_list")

    def action_new_project(self) -> None:
        self.app.push_screen(OnboardingScreen())

    def action_expand(self) -> None:
        if not self._ensure_project():
            self.notify("请先选择或创建项目", severity="warning")
            return

        def on_done(success: bool) -> None:
            if success:
                self._refresh()
                self.notify("组织树已更新", title="扩建完成", severity="information")

        self.app.push_screen(ExpandScreen(self.project_name), on_done)

    def action_quit(self) -> None:
        self.app.exit()


def _build_agent_status(root: Path, positions: list[dict]) -> str:
    """构建 Agent 启用状态摘要文本。"""
    agent_ids: set[str] = set()
    for pos in positions:
        aid = pos.get("agent", "")
        if aid:
            agent_ids.add(aid)
    if not agent_ids:
        return ""
    enabled_count = sum(1 for aid in agent_ids if agent_enabled(root, aid))
    total = len(agent_ids)
    if enabled_count == total:
        return f" · Agent [green]{enabled_count}/{total} 已启用[/]"
    else:
        disabled = total - enabled_count
        return f" · Agent [green]{enabled_count}[/]/[red]{disabled} 已禁用[/]（{total}）"
