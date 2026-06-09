# cli/tui/screens/agent_list.py — 热门 Agent 目录：单击看详情，双击安装/打开
from __future__ import annotations

import time
from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.containers import Container, Vertical, VerticalScroll
from textual.events import Click
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Footer, Header, Label, ListItem, ListView, Static

from agents.goose_env import goose_setup_command
from core.config.agent_catalog import (
    AgentCatalogRow,
    build_agent_catalog,
    catalog_row_can_open,
    catalog_summary,
    clear_catalog_build_cache,
    invalidate_agent_catalog_cache,
    is_catalog_agent_installed,
)
from core.config.agent_policy import agent_enabled, set_agent_enabled
from core.project import get_project_root, get_studio_root, list_registered_projects, resolve_project_id
from core.terminal.agent_launcher import spawn_agent_tui, spawn_catalog_command_tui
from core.terminal.install_launcher import is_runnable_install_cmd, spawn_install_terminal


class AgentListScreen(Screen):
    """热门 Agent 列表：单击查看详情，双击安装或打开 TUI。"""

    BINDINGS = [
        ("enter", "activate_selected", "执行"),
        ("e", "toggle_enabled", "启用/禁用"),
        ("r", "refresh", "刷新"),
        ("tab", "focus_detail", "详情滚动"),
        ("escape", "back", "返回"),
        ("q", "quit", "退出"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[AgentCatalogRow] = []
        self._active_index: int = 0
        self._busy: bool = False
        self._loading: bool = False
        self._detail_cache: dict[str, str] = {}
        self._label_cache: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Container(
            Vertical(
                Static("[bold]Agent 目录[/]", classes="title-text"),
                Static("", id="agent-stats", classes="accent"),
                ListView(id="agent-list"),
                VerticalScroll(
                    Static("", id="agent-detail"),
                    id="agent-detail-scroll",
                    classes="panel-box",
                ),
                Static("", id="agent-status", classes="muted"),
                id="agent-box",
            ),
            id="agent-container",
        )
        yield Footer()

    def on_mount(self) -> None:
        self._load_catalog_async(refresh_path=False, probe_versions=False)

    def on_screen_resume(self) -> None:
        # 从安装终端返回：仅轻量刷新安装状态，不探测版本
        self._load_catalog_async(refresh_path=True, probe_versions=False)

    @work(thread=True, exclusive=True)
    def _load_catalog_worker(
        self,
        *,
        refresh_path: bool,
        probe_versions: bool,
        network_versions: bool,
    ) -> None:
        root = get_studio_root()
        if refresh_path:
            invalidate_agent_catalog_cache(refresh_path=True)
        else:
            clear_catalog_build_cache()
        rows = build_agent_catalog(
            root,
            force=True,
            refresh_path=refresh_path,
            probe_versions=probe_versions,
            network_versions=network_versions,
        )
        self.app.call_from_thread(self._apply_catalog_rows, rows, probe_versions)

    def _load_catalog_async(
        self,
        *,
        refresh_path: bool,
        probe_versions: bool,
        network_versions: bool = False,
    ) -> None:
        if self._loading:
            return
        self._loading = True
        if probe_versions:
            self._set_status("正在刷新版本信息…")
        elif not self._rows:
            self._set_status("正在加载 Agent 目录…")
        self._load_catalog_worker(
            refresh_path=refresh_path,
            probe_versions=probe_versions,
            network_versions=network_versions,
        )

    def _apply_catalog_rows(self, rows: list[AgentCatalogRow], versions_loaded: bool) -> None:
        self._loading = False
        self._rows = rows
        self._detail_cache.clear()
        self._label_cache.clear()
        prev = self._active_index

        stats = catalog_summary(rows)
        updates = sum(1 for r in rows if r.update_available)
        stats_line = (
            f"已安装 {stats['installed']}/{stats['total']} · "
            f"可打开 {stats['openable_installed']} 个"
        )
        if updates:
            stats_line += f" · [yellow]{updates} 个可更新[/]"
        self.query_one("#agent-stats", Static).update(stats_line)

        list_view = self.query_one("#agent-list", ListView)
        list_view.remove_children()
        if not rows:
            list_view.append(ListItem(Label("[dim]目录为空，请检查 config/agents_catalog.yaml[/]")))
            self.query_one("#agent-detail", Static).update("")
            self._set_status("")
            return

        for row in rows:
            list_view.append(ListItem(Label(self._list_label(row))))

        self._active_index = min(prev, len(rows) - 1)
        list_view.index = self._active_index
        list_view.focus()
        self._update_detail()
        if versions_loaded:
            self.notify("版本信息已更新", severity="information")
            self._set_status("版本信息已更新")

    def _sync_index_from_list(self) -> None:
        list_view = self.query_one("#agent-list", ListView)
        if list_view.index is not None and 0 <= list_view.index < len(self._rows):
            self._active_index = list_view.index

    def _set_status(self, message: str, *, error: bool = False) -> None:
        prefix = "[red]" if error else "[dim]"
        self.query_one("#agent-status", Static).update(f"{prefix}{message}[/]")

    def _row_action_hint(self, row: AgentCatalogRow) -> str:
        if row.update_available and is_runnable_install_cmd(row.install_cmd):
            return "有新版本，双击在终端运行更新命令"
        if row.needs_configure:
            return "双击运行 goose configure 配置 provider"
        if catalog_row_can_open(row):
            return "双击打开 Agent TUI"
        if not row.installed and is_runnable_install_cmd(row.install_cmd):
            return "双击在终端运行安装命令"
        if not row.installed:
            return "请手动安装"
        if row.launch_error:
            return row.launch_error
        return "请查看 docs/INSTALL-AGENTS.md"

    def _format_version_line(self, row: AgentCatalogRow) -> str:
        if row.installed and row.installed_version:
            line = f"[bold]当前版本:[/] [green]{row.installed_version}[/]"
            if row.latest_version:
                line += f"  ·  最新 [cyan]{row.latest_version}[/]"
            if row.update_available:
                line += "  [yellow]↑ 可更新[/]"
            return line
        if row.latest_version:
            return f"[bold]最新版本:[/] [cyan]{row.latest_version}[/]（未安装）"
        if row.installed:
            return "[bold]版本:[/] [dim]按 R 刷新版本[/]"
        return ""

    def _list_label(self, row: AgentCatalogRow) -> str:
        cached = self._label_cache.get(row.id)
        if cached:
            return cached
        root = get_studio_root()
        if row.update_available:
            status = "[yellow]↑ 可更新[/]"
        elif catalog_row_can_open(row):
            status = "[green]● 可打开[/]"
        elif row.needs_configure:
            status = "[yellow]● 需配置[/]"
        elif row.installed:
            status = "[green]● 已安装[/]"
        else:
            status = "[dim]○ 未安装[/]"
        # 启用/禁用标记
        if row.agent_id:
            enabled = agent_enabled(root, row.agent_id)
            toggle = "[green]⊚ 已启用[/]" if enabled else "[red]⊗ 已禁用[/]"
        else:
            toggle = "[dim]—[/]"
        byok = "[cyan]BYOK[/]" if row.byok else "[yellow]订阅[/]"
        ver = ""
        if row.installed_version:
            ver = f"  [dim]v{row.installed_version}[/]"
        elif row.latest_version and not row.installed:
            ver = f"  [dim]最新 v{row.latest_version}[/]"
        text = f"{status}  [bold]{row.name}[/]{ver}  {byok}  {toggle}\n[dim]{row.tagline}[/]"
        self._label_cache[row.id] = text
        return text

    def _format_detail(self, row: AgentCatalogRow) -> str:
        cached = self._detail_cache.get(row.id)
        if cached:
            return cached
        lines = [
            f"[bold]{row.name}[/]  ({row.id})",
            f"命令: [cyan]{row.command or '—'}[/]",
            f"[bold]操作:[/] [accent]{self._row_action_hint(row)}[/]",
        ]
        ver_line = self._format_version_line(row)
        if ver_line:
            lines.append(ver_line)
        if row.command_path:
            lines.append(f"路径: [dim]{row.command_path}[/]")
        lines.append(f"模型: {'BYOK / 第三方 API' if row.byok else '厂商订阅'}")
        lines.append(f"[bold]API Key:[/] {row.apikey_hint}")
        if row.launch_error:
            lines.append(f"[bold]状态:[/] [red]{row.launch_error}[/]")
        if row.update_available and row.install_cmd:
            lines.append(
                f"[bold]更新:[/] [yellow]{row.install_cmd}[/]  "
                f"（与安装命令相同，会安装最新版）"
            )
        elif row.install_cmd:
            label = "安装命令" if is_runnable_install_cmd(row.install_cmd) else "安装方式"
            lines.append(f"[bold]{label}:[/] [yellow]{row.install_cmd}[/]")
        text = "\n".join(lines)
        self._detail_cache[row.id] = text
        return text

    def _selected_row(self) -> AgentCatalogRow | None:
        if not self._rows:
            return None
        idx = self._active_index
        if idx < 0 or idx >= len(self._rows):
            idx = 0
            self._active_index = 0
        return self._rows[idx]

    def _update_detail(self) -> None:
        row = self._selected_row()
        if not row:
            return
        self.query_one("#agent-detail", Static).update(self._format_detail(row))
        self._set_status(
            f"[{self._active_index + 1}/{len(self._rows)}] {row.name} · "
            f"{self._row_action_hint(row)}"
        )

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id != "agent-list" or not self._rows:
            return
        if event.list_view.index is not None and event.list_view.index != self._active_index:
            self._active_index = event.list_view.index
            self._update_detail()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id != "agent-list" or not self._rows:
            return
        if event.list_view.index is not None:
            self._active_index = event.list_view.index
            self._update_detail()

    def _click_in_agent_list(self, widget: Widget) -> bool:
        node: Widget | None = widget
        while node is not None:
            if getattr(node, "id", None) == "agent-list":
                return True
            node = node.parent
        return False

    def on_click(self, event: Click) -> None:
        if event.chain < 2:
            return
        if not self._click_in_agent_list(event.widget):
            return
        self._sync_index_from_list()
        self.action_activate_selected()

    def _resolve_worktree(self, root: Path) -> Path:
        project_name = getattr(self.app, "project_name", None)
        if project_name:
            try:
                return get_project_root(root, project_name)
            except (FileNotFoundError, KeyError, ValueError):
                pass
        try:
            pid = resolve_project_id(root)
            return get_project_root(root, pid)
        except (FileNotFoundError, KeyError, ValueError):
            return root

    def action_activate_selected(self) -> None:
        if self._busy or self._loading:
            return
        self._sync_index_from_list()
        row = self._selected_row()
        if not row:
            self._set_status("没有可选 Agent", error=True)
            return

        if row.update_available and is_runnable_install_cmd(row.install_cmd):
            self._busy = True
            self._set_status(f"正在打开更新终端: {row.install_cmd}")
            self._spawn_install_worker(row)
            return

        if row.needs_configure:
            self._busy = True
            self._set_status("正在打开 Goose 配置向导 (goose configure)…")
            self._spawn_install_worker(row, goose_setup_command())
            return

        if catalog_row_can_open(row):
            self._busy = True
            self._set_status(f"正在打开 {row.name}…")
            self._spawn_agent_worker(row)
            return

        if not row.installed and is_runnable_install_cmd(row.install_cmd):
            self._busy = True
            self._set_status(f"正在打开安装终端: {row.install_cmd}")
            self._spawn_install_worker(row)
            return

        if row.installed and row.launch_error:
            self._set_status(row.launch_error, error=True)
        elif row.install_cmd:
            self._set_status(f"请手动安装: {row.install_cmd}", error=True)
        else:
            self._set_status(f"{row.name} 无可用安装命令", error=True)

    @work(thread=True, exclusive=True)
    def _spawn_agent_worker(self, row: AgentCatalogRow) -> None:
        root = get_studio_root()
        cwd = self._resolve_worktree(root)
        try:
            if row.agent_id and row.openable:
                spawn_agent_tui(
                    root,
                    row.agent_id,
                    cwd,
                    title=f"Studio · {row.name}",
                    prompt=(
                        f"Studio Agent 目录已为你打开 {row.name}。\n"
                        f"请在本终端内自行配置 API Key / 模型，然后开始工作。"
                    ),
                    role=row.name,
                    respect_policy=False,
                )
            else:
                spawn_catalog_command_tui(
                    row.command,
                    cwd,
                    title=f"Studio · {row.name}",
                    resolved_path=row.command_path,
                )
        except RuntimeError as exc:
            self.app.call_from_thread(self._on_action_failed, str(exc))
            return
        self.app.call_from_thread(self._on_open_done, row.name)

    @work(thread=True, exclusive=True)
    def _spawn_install_worker(self, row: AgentCatalogRow, cmd: str | None = None) -> None:
        root = get_studio_root()
        cwd = self._resolve_worktree(root)
        install_cmd = cmd or row.install_cmd
        try:
            spawn_install_terminal(
                f"Studio · 安装 {row.name}" if not cmd else f"Studio · 配置 {row.name}",
                install_cmd,
                cwd,
            )
        except RuntimeError as exc:
            self.app.call_from_thread(self._on_action_failed, str(exc))
            return
        if cmd and "configure" in cmd.lower():
            self.app.call_from_thread(self._on_configure_started, row.name)
        else:
            self.app.call_from_thread(self._on_install_started, row.id, row.name)

    def _on_open_done(self, name: str) -> None:
        self._busy = False
        self.notify(f"已打开 {name} TUI", title="Agent", severity="information")
        self._set_status(f"已打开 {name}")

    def _on_install_started(self, row_id: str, name: str) -> None:
        self._busy = False
        self.notify(f"已打开 {name} 安装终端", title="安装", severity="information")
        self._watch_install_worker(row_id, name)
        self._set_status(f"等待 {name} 安装完成…")

    @work(thread=True, exclusive=True)
    def _watch_install_worker(self, row_id: str, name: str) -> None:
        """轻量轮询单条安装状态，避免全量版本探测卡死 UI。"""
        root = get_studio_root()
        for _ in range(24):
            time.sleep(5)
            if is_catalog_agent_installed(root, row_id, refresh_path=True):
                self.app.call_from_thread(self._on_install_detected, name)
                return

    def _on_install_detected(self, name: str) -> None:
        self._load_catalog_async(refresh_path=True, probe_versions=False)
        self.notify(f"{name} 已安装", title="安装", severity="information")

    def _on_configure_started(self, name: str) -> None:
        self._busy = False
        self.notify(f"已打开 {name} 配置向导", title="配置", severity="information")
        self._set_status(f"完成 {name} 配置后按 Esc 返回并自动刷新")

    def _on_action_failed(self, message: str) -> None:
        self._busy = False
        self._set_status(message, error=True)

    def action_refresh(self) -> None:
        self._load_catalog_async(
            refresh_path=True,
            probe_versions=True,
            network_versions=True,
        )

    def action_focus_detail(self) -> None:
        self.query_one("#agent-detail-scroll", VerticalScroll).focus()

    def action_toggle_enabled(self) -> None:
        """切换当前选中 Agent 的启用/禁用状态。"""
        if self._busy or self._loading:
            return
        self._sync_index_from_list()
        row = self._selected_row()
        if not row or not row.agent_id:
            self._set_status("此 Agent 不支持启用/禁用", error=True)
            return
        root = get_studio_root()
        current = agent_enabled(root, row.agent_id)
        set_agent_enabled(root, row.agent_id, not current)
        new_state = agent_enabled(root, row.agent_id)
        state_text = "已启用" if new_state else "已禁用（调度时自动走 mock）"
        self._label_cache.clear()
        self._detail_cache.clear()
        self.notify(f"{row.name}: {state_text}", title="Agent 开关", severity="information")
        self._set_status(f"{row.name} {state_text}")
        # 刷新列表显示
        list_view = self.query_one("#agent-list", ListView)
        list_view.remove_children()
        for r in self._rows:
            list_view.append(ListItem(Label(self._list_label(r))))
        list_view.index = self._active_index
        self._update_detail()

    def action_back(self) -> None:
        if getattr(self.app, "project_name", None):
            self.app.switch_screen("dashboard")
        elif list_registered_projects(get_studio_root()):
            self.app.switch_screen("project_hub")
        else:
            self.app.switch_screen("welcome")

    def action_quit(self) -> None:
        self.app.exit()
