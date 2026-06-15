# cli/tui/screens/dashboard.py — CEO 指挥舱
from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Input, ProgressBar, Static

from cli.tui.screens.briefing import TaskDispatchScreen
from cli.tui.screens.expand import ExpandScreen
from cli.tui.screens.onboarding import OnboardingScreen
from cli.tui.widgets.message_log import render_agent_activity, render_message_log
from cli.tui.widgets.org_tree import render_org_tree
from cli.tui.widgets.orchestration_panel import render_orchestration_panel
from cli.tui.widgets.task_panel import render_task_panel
from core.config.agent_policy import agent_enabled
from core.dispatch.briefing import load_brief, mark_brief_dispatched
from core.dispatch.dispatcher import get_dispatcher
from core.dispatch.orchestration_progress import compute_orchestration_progress
from core.ipc.ceo_chat import send_ceo_feedback
from core.ipc.message_log import MessageLogCollector
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
        ("c", "open_chat", "通信"),
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
        self._msg_collector: MessageLogCollector | None = None
        self._message_history: list = []  # list[MessageRecord]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("", id="dash-status-bar")
        yield Horizontal(
            Static("", id="org-panel"),
            Static("", id="task-panel"),
            id="main-panels",
        )
        # 底部栏：编排进度 + Agent 状态 + 消息日志 + 聊天输入
        yield VerticalScroll(
            Static("", id="orch-panel-text"),
            ProgressBar(total=100, show_eta=False, id="orch-progress"),
            Static("", id="agent-activity"),
            Static("", id="message-log"),
            Input(placeholder="输入消息按回车发送给主管…", id="ceo-chat-input"),
            id="bottom-bar",
        )
        yield Footer()

    # ── 生命周期 ──

    def on_mount(self) -> None:
        if not self.project_name and getattr(self.app, "project_name", None):
            self.project_name = self.app.project_name
        self._hide_orch_parts()
        self.set_interval(1.5, self._refresh)
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
        self._refresh()

    # ── 编排区显示/隐藏 ──

    def _hide_orch_parts(self) -> None:
        """隐藏编排专属元素（进度条 + 聊天框）。"""
        self.query_one("#orch-panel-text").display = False
        self.query_one("#orch-progress").display = False
        self.query_one("#ceo-chat-input").display = False

    def _show_orch_parts(self) -> None:
        """显示编排专属元素。"""
        self.query_one("#orch-panel-text").display = True
        self.query_one("#orch-progress").display = True

    # ── 项目同步 ──

    def _sync_project_name(self) -> bool:
        root = get_studio_root()
        if self.app.screen is not self:
            # 非活跃屏幕：只从 app 同步自身，不写回（防止旧 dashboard 覆盖新项目）
            app_name = getattr(self.app, "project_name", None)
            if app_name and app_name != self.project_name:
                self.project_name = app_name
            return bool(self.project_name)
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
        self.project_name = None
        self.app.project_name = None
        self._pending_task_id = None
        self._pending_description = ""
        self.query_one("#org-panel", Static).update("[dim]（无项目）[/]")
        self.query_one("#task-panel", Static).update(
            "[dim]当前项目已删除或不可用。[/]\n按 [bold]P[/] 打开项目中心选择或新建项目。"
        )
        self._hide_orch_parts()
        self.query_one("#agent-activity", Static).update("")
        self.query_one("#message-log", Static).update("")
        self.query_one("#dash-status-bar", Static).update(
            "  [bold red]当前项目已不存在，按 P 打开项目中心[/]"
        )

    def _ensure_project(self) -> bool:
        if self._sync_project_name():
            return True
        self._show_no_project()
        return False

    # ── 编排启动 ──

    def _start_orchestration(self, description: str) -> None:
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
            self.query_one("#dash-status-bar", Static).update(f"  [red]下达失败: {exc}[/]")

    # ── 编排进度刷新 ──

    def _update_orchestration_ui(self, disp, root: Path) -> None:
        if not self._pending_task_id:
            self._hide_orch_parts()
            return

        disp.try_complete_orchestration(root, self._pending_task_id, spawn_terminals=True)

        prog = compute_orchestration_progress(
            disp.project_dir,
            self._pending_task_id,
            description=self._pending_description,
            tasks=disp.get_status(),
            states=disp.get_agent_states(),
        )
        self._show_orch_parts()
        self.query_one("#orch-panel-text", Static).update(render_orchestration_panel(prog))
        bar = self.query_one("#orch-progress", ProgressBar)
        bar.progress = prog.percent

        color = ("red" if prog.failed else "green" if prog.done
                 else "cyan" if prog.percent >= 50 else "yellow")
        self.query_one("#dash-status-bar", Static).update(
            f"  [{color}]编排 {prog.percent}% — {prog.message}[/]"
        )

        self._update_comm_hub(disp, show_chat=True)

        if prog.done:
            self.notify(f"编排完成：{prog.message}", title="任务完成", severity="information")
            self._pending_task_id = None
            self._pending_description = ""
            self._hide_orch_parts()
        elif prog.failed:
            self.notify(prog.message, title="编排失败", severity="error")
            self._pending_task_id = None
            self._pending_description = ""
            self._hide_orch_parts()

    # ── 通信中枢 ──

    def _update_comm_hub(self, disp, *, show_chat: bool = False) -> None:
        project_dir = disp.project_dir

        if self._msg_collector is None or self._msg_collector.project_dir != project_dir:
            self._msg_collector = MessageLogCollector(project_dir)
            self._message_history.clear()

        new_records = self._msg_collector.collect_new()
        if new_records:
            self._message_history.extend(new_records)
            if len(self._message_history) > 200:
                self._message_history = self._message_history[-200:]

        self.query_one("#message-log", Static).update(
            render_message_log(self._message_history[-50:])
        )

        positions = disp.list_positions()
        states = disp.get_agent_states()
        self.query_one("#agent-activity", Static).update(
            render_agent_activity(positions, states)
        )

        self.query_one("#ceo-chat-input").display = show_chat

    def _on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "ceo-chat-input":
            return
        text = event.value.strip()
        if not text:
            return

        root = get_studio_root()
        if not self._sync_project_name():
            return

        disp = get_dispatcher(root, self.project_name)
        try:
            manager_id = disp._root_manager_id()
        except RuntimeError:
            self.notify("未找到主管", severity="warning")
            return

        send_ceo_feedback(
            project_dir=disp.project_dir,
            manager_id=manager_id,
            text=text,
            task_id=self._pending_task_id or "",
        )
        event.input.value = ""
        self.notify("已发送给主管", severity="information")

    def action_open_chat(self) -> None:
        """打开主管聊天频道。"""
        if not self._ensure_project():
            self.notify("请先选择或创建项目", severity="warning")
            return
        self.app.push_screen("chat")

    # ── 主刷新 ──

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
            render_task_panel(tasks, positions, states, highlight_task_id=self._pending_task_id)
        )

        if self._pending_task_id:
            self._update_orchestration_ui(disp, root)
            return

        self._hide_orch_parts()
        self._update_comm_hub(disp)

        sup = "Supervisor ✓" if SupervisorClient(root).health() else "Supervisor …"
        mgr_pending = len(disp.get_manager_reviews())
        ceo_pending = len(disp.get_pending_reviews())
        awaiting_delivery = sum(
            1 for t in tasks
            if t.get("status") in ("assigned", "in_progress", "submitted") and t.get("assignee")
        )
        agent_status = _build_agent_status(root, positions)

        parts = [f"[bold cyan]{self.project_name}[/]", f"[dim]{project_root}[/]", sup]
        if agent_status:
            parts.append(agent_status)
        if awaiting_delivery:
            parts.append(f"[bold yellow]◆ Worker 执行中 {awaiting_delivery}[/]")
        if mgr_pending:
            parts.append(f"[yellow]主管审查中 {mgr_pending}[/]")
        if ceo_pending:
            parts.append(f"[bold yellow]◆ CEO 待批 {ceo_pending}[/]")
        parts.append("[dim]N 下达任务[/]")
        self.query_one("#dash-status-bar", Static).update("  " + " · ".join(parts))

    # ── 快捷键动作 ──

    def action_refresh(self) -> None:
        self._refresh()

    def action_dispatch_task(self) -> None:
        def on_done(final_task: str | None) -> None:
            if final_task:
                self._start_orchestration(final_task)

        if not self._ensure_project():
            self.notify("请先选择或创建项目", severity="warning")
            return
        self.app.push_screen(
            TaskDispatchScreen(project_name=self.project_name, is_new=False), on_done
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
        self.app.switch_screen(OnboardingScreen())

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
