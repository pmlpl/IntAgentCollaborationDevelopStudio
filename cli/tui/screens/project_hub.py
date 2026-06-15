# cli/tui/screens/project_hub.py — 项目中心：增删改查
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Label, ListItem, ListView, Static

from cli.tui.screens.onboarding import OnboardingScreen
from cli.tui.screens.project_delete import ProjectDeleteModal
from cli.tui.screens.project_edit import ProjectEditModal
from core.project import (
    clear_stale_current_project,
    delete_project,
    get_studio_root,
    list_registered_projects,
    set_current_project,
)


class ProjectHubScreen(Screen):
    """项目列表：查 / 增 / 改 / 删。"""

    BINDINGS = [
        ("enter", "open_selected", "打开"),
        ("n", "new_project", "新建"),
        ("e", "edit_selected", "编辑"),
        ("delete", "delete_selected", "删除"),
        ("o", "open_selected", "打开"),
        ("escape", "back", "返回"),
        ("q", "quit", "退出"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._projects: list[dict] = []
        self._active_index: int = 0
        self._reload_scheduled: bool = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Container(
            VerticalScroll(
                Static("[bold]项目中心[/]", classes="title-text"),
                Static(
                    "↑↓ 选中 · Enter/O 打开 · N 新建 · E 编辑 · Del 删除 · Esc 返回",
                    classes="page-hint",
                ),
                ListView(id="project-list"),
                Static("", id="hub-status", classes="muted"),
                id="hub-box",
                classes="page-body",
            ),
            id="hub-container",
            classes="page-shell",
        )
        yield Footer()

    def on_mount(self) -> None:
        self._request_reload()

    def on_screen_resume(self) -> None:
        self._request_reload()

    def _request_reload(self) -> None:
        """合并 on_mount / on_screen_resume 同帧触发的重复刷新。"""
        if self._reload_scheduled:
            return
        self._reload_scheduled = True

        def _do_reload() -> None:
            self._reload_scheduled = False
            self._reload_list()

        self.call_after_refresh(_do_reload)

    def _sync_index_from_list(self) -> None:
        """从 ListView 同步索引。"""
        list_view = self.query_one("#project-list", ListView)
        if list_view.index is not None and 0 <= list_view.index < len(self._projects):
            self._active_index = list_view.index

    def _set_status(self, message: str, *, error: bool = False) -> None:
        prefix = "[red]" if error else "[dim]"
        suffix = "[/]" if error else "[/]"
        self.query_one("#hub-status", Static).update(f"{prefix}{message}{suffix}")

    def _reload_list(self) -> None:
        root = get_studio_root()
        prev = self._active_index
        self._projects = list_registered_projects(root)
        list_view = self.query_one("#project-list", ListView)
        list_view.remove_children()
        if not self._projects:
            self._active_index = 0
            list_view.append(ListItem(Label("[dim]暂无项目，按 N 新建[/]")))
            self._set_status("")
            return

        for entry in self._projects:
            purpose = entry.get("purpose") or "—"
            path = entry.get("path") or "—"
            title = entry.get("name") or entry.get("id")
            list_view.append(
                ListItem(
                    Label(f"[bold]{title}[/]  [dim]({entry['id']})[/]\n{purpose}\n{path}"),
                )
            )

        self._active_index = min(prev, len(self._projects) - 1)
        list_view.index = self._active_index
        list_view.focus()
        self._update_selection_hint()

    def _selected_project(self, *, required: bool = False) -> dict | None:
        """使用 _active_index，不依赖 ListView 在失焦后仍保留 index。"""
        if not self._projects:
            if required:
                self._set_status("没有可操作的项目", error=True)
            return None

        idx = self._active_index
        if idx < 0 or idx >= len(self._projects):
            if required:
                self._set_status("请先用 ↑↓ 或鼠标选中要操作的项目", error=True)
                return None
            idx = 0
            self._active_index = 0

        return self._projects[idx]

    def _update_selection_hint(self) -> None:
        entry = self._selected_project()
        if not entry:
            return
        title = entry.get("name") or entry.get("id")
        self._set_status(
            f"当前选中 [{self._active_index + 1}/{len(self._projects)}]: "
            f"{title} ({entry.get('id')})"
        )

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id != "project-list" or not self._projects:
            return
        if event.list_view.index is not None:
            self._active_index = event.list_view.index
            self._update_selection_hint()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """单击/回车选中：只更新索引，不自动打开（避免点选时误进指挥舱）。"""
        if event.list_view.id != "project-list" or not self._projects:
            return
        if event.list_view.index is not None:
            self._active_index = event.list_view.index
            self._update_selection_hint()

    def _open_project(self, entry: dict) -> None:
        root = get_studio_root()
        project_id = entry["id"]
        set_current_project(root, project_id)
        self.app.project_name = project_id
        self.app.switch_screen("dashboard")

    def action_open_selected(self) -> None:
        self._sync_index_from_list()
        entry = self._selected_project()
        if entry:
            self._open_project(entry)

    def action_new_project(self) -> None:
        self.app.switch_screen(OnboardingScreen())

    def action_edit_selected(self) -> None:
        self._sync_index_from_list()
        entry = self._selected_project(required=True)
        if not entry:
            return

        def on_done(saved: bool) -> None:
            if saved:
                self._request_reload()

        self.app.push_screen(ProjectEditModal(entry), on_done)

    def action_delete_selected(self) -> None:
        self._sync_index_from_list()
        entry = self._selected_project(required=True)
        if not entry:
            return

        # 闭包捕获当前选中项，避免确认框期间索引被重置
        target = dict(entry)

        def on_done(confirmed: bool) -> None:
            if not confirmed:
                self._set_status("已取消删除")
                return
            root = get_studio_root()
            project_id = target["id"]
            try:
                folder_deleted, warning = delete_project(root, project_id, remove_folder=True)
            except ValueError as exc:
                self._set_status(str(exc), error=True)
                return
            if getattr(self.app, "project_name", None) == project_id:
                self.app.project_name = None
            clear_stale_current_project(root, project_id)
            try:
                dashboard = self.app.get_screen("dashboard")
                if getattr(dashboard, "project_name", None) == project_id:
                    dashboard.project_name = None
                    if hasattr(dashboard, "_show_no_project"):
                        dashboard._show_no_project()
            except Exception:
                pass
            if warning:
                self._set_status(warning, error=True)
                self.notify(warning, title="部分完成", severity="warning")
            else:
                self._set_status(f"已删除: {target.get('name') or project_id}")
            self._request_reload()

        self.app.push_screen(ProjectDeleteModal(target), on_done)

    def action_back(self) -> None:
        if getattr(self.app, "project_name", None):
            self.app.switch_screen("dashboard")
        else:
            self.app.switch_screen("welcome")

    def action_quit(self) -> None:
        self.app.exit()
