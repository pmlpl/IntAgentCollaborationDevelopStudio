"""主管聊天频道 — CEO ↔ Manager 全场景对话界面。"""
from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, RichLog, Static

from cli.tui.widgets.chat_input import (
    ChatInput,
    SlashCommand,
    render_chat_message,
    parse_slash_command,
    COMMANDS,
)
from core.dispatch.dispatcher import get_dispatcher
from core.ipc.ceo_chat import send_ceo_feedback
from core.ipc.message_log import MessageLogCollector


class ChatScreen(Screen):
    """主管聊天频道。"""
    BINDINGS = [
        ("escape", "back", "返回"),
        ("ctrl+home", "scroll_top", "顶部"),
        ("ctrl+end", "scroll_bottom", "底部"),
        ("s", "show_status", "状态"),
        ("e", "show_escalations", "升级"),
    ]

    def __init__(
        self,
        project_dir: str | Path | None = None,
        manager_id: str = "",
        task_id: str | None = None,
    ) -> None:
        super().__init__()
        self._project_dir = Path(project_dir) if project_dir else None
        self._manager_id = manager_id
        self._task_id = task_id or ""
        self._collector: MessageLogCollector | None = None
        self._auto_scroll: bool = True
        self._last_task_state: str | None = None

    # ── 布局 ──

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(self._build_header_text(), id="chat-header")
        yield RichLog(id="chat-messages", wrap=True, highlight=True)
        yield Static("", id="chat-status")
        yield ChatInput(
            agent_ids=self._agent_ids(),
            placeholder="输入指令… Tab:补全 /:命令",
            id="chat-input",
        )
        yield Footer()

    def _build_header_text(self) -> str:
        parts = ["📡 主管频道"]
        if self._manager_id:
            parts.append(f"Manager: {self._manager_id}")
        if self._task_id:
            parts.append(f"任务: {self._task_id}")
        parts.append("esc:返回")
        return " │ ".join(parts)

    def _agent_ids(self) -> list[str]:
        """获取当前项目中的 Agent ID 列表（用于 @ 补全）。"""
        if not self._project_dir:
            return []
        agents_dir = self._project_dir / "agents"
        if not agents_dir.exists():
            return []
        return sorted(d.name for d in agents_dir.iterdir() if d.is_dir())

    # ── 生命周期 ──

    def on_mount(self) -> None:
        """初始化 collector + 加载历史 + 启动轮询。"""
        self._sync_context()
        if self._project_dir:
            self._collector = MessageLogCollector(self._project_dir)
            self._load_history()
        self.set_interval(2.0, self._poll_messages)

    def _sync_context(self) -> None:
        """从 StudioApp 获取项目上下文。"""
        if self._project_dir:
            return
        try:
            app = self.app
            project_name = getattr(app, "project_name", None)
            if project_name:
                from core.project import get_studio_root
                root = get_studio_root()
                disp = get_dispatcher(root, project_name)
                self._project_dir = disp.project_dir
                self._manager_id = disp._root_manager_id()
        except Exception:
            pass

    def _load_history(self) -> None:
        """加载最近 30 条消息到 RichLog。"""
        if not self._collector:
            return
        records = self._collector.collect_new(limit_per_agent=15)
        if not records:
            return
        recent = records[-30:]
        rich_log = self.query_one("#chat-messages", RichLog)
        rich_log.write(
            "[dim]── 会话开始 ──[/]\n",
            scroll_end=False,
        )
        for rec in recent:
            rich_log.write(
                render_chat_message(rec) + "\n",
                scroll_end=False,
            )

    # ── 轮询 ──

    def _poll_messages(self) -> None:
        """每 2 秒轮询新消息。"""
        if not self._collector:
            return

        new_records = self._collector.collect_new()
        if new_records:
            rich_log = self.query_one("#chat-messages", RichLog)
            for rec in new_records:
                rich_log.write(render_chat_message(rec) + "\n", scroll_end=self._auto_scroll)

        self._check_task_state()

    def _check_task_state(self) -> None:
        """检查任务状态变化，生成系统消息。"""
        if not self._project_dir:
            return
        try:
            app = self.app
            project_name = getattr(app, "project_name", None)
            if not project_name:
                return
            from core.project import get_studio_root
            root = get_studio_root()
            disp = get_dispatcher(root, project_name)
            if self._task_id:
                task = disp.load_task(self._task_id)
                state = task.get("state", "") if task else ""
                if state and state != self._last_task_state:
                    self._last_task_state = state
                    rich_log = self.query_one("#chat-messages", RichLog)
                    rich_log.write(
                        f"[#f9ca24]│[/] [#f9ca24]🔔 系统[/]\n"
                        f"[#f9ca24]│[/]    任务 {self._task_id} 状态变更: {state}\n",
                        scroll_end=self._auto_scroll,
                    )
        except Exception:
            pass

    # ── 发送消息 ──

    def on_input_submitted(self, event) -> None:
        """处理输入提交。"""
        if event.input.id != "chat-input":
            return
        text = event.value.strip()
        if not text:
            return

        input_widget = self.query_one("#chat-input", ChatInput)
        input_widget.push_history(text)

        cmd = parse_slash_command(text)
        if cmd:
            self._handle_slash_command(cmd)
        else:
            self._send_to_manager(text)

        input_widget.value = ""

    def _send_to_manager(self, text: str) -> None:
        """发送自然语言消息给 Manager。"""
        if not self._project_dir or not self._manager_id:
            self.notify("未连接到项目或 Manager", severity="warning")
            return

        send_ceo_feedback(
            project_dir=self._project_dir,
            manager_id=self._manager_id,
            text=text,
            task_id=self._task_id,
        )

        rich_log = self.query_one("#chat-messages", RichLog)
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).strftime("%H:%M:%S")
        rich_log.write(
            f"[#ff6b9d]👤 CEO[/] [dim]{now}[/]\n"
            f"   {text}\n",
            scroll_end=self._auto_scroll,
        )
        self.notify("已发送给主管", severity="information")

    def _handle_slash_command(self, cmd: SlashCommand) -> None:
        """处理斜杠命令。"""
        handler = getattr(self, f"_cmd_{cmd.name}", None)
        if handler:
            handler(cmd.args)
        else:
            self.notify(f"未知命令: /{cmd.name}", severity="warning")

    def _cmd_status(self, args: str) -> None:
        self._show_system_message("正在获取状态…")
        self.notify("状态已刷新", severity="information")

    def _cmd_escalations(self, args: str) -> None:
        self._show_system_message("查看待决策升级…")

    def _cmd_clear(self, args: str) -> None:
        rich_log = self.query_one("#chat-messages", RichLog)
        rich_log.clear()
        rich_log.write("[dim]── 屏幕已清空 ──[/]\n")

    def _cmd_help(self, args: str) -> None:
        lines = ["[#f9ca24]│[/] [#f9ca24]🔔 命令帮助[/]"]
        for name, desc in COMMANDS.items():
            lines.append(f"[#f9ca24]│[/]   [bold]/{name}[/] — {desc}")
        rich_log = self.query_one("#chat-messages", RichLog)
        rich_log.write("\n".join(lines) + "\n", scroll_end=self._auto_scroll)

    def _cmd_history(self, args: str) -> None:
        try:
            n = int(args) if args else 30
        except ValueError:
            n = 30
        if not self._collector:
            return
        self._collector.reset()
        records = self._collector.collect_new(limit_per_agent=n)
        recent = records[-n:]
        rich_log = self.query_one("#chat-messages", RichLog)
        for rec in recent:
            rich_log.write(render_chat_message(rec) + "\n", scroll_end=False)
        self.notify(f"已加载 {len(recent)} 条历史消息", severity="information")

    def _cmd_filter(self, args: str) -> None:
        self.notify(f"过滤功能开发中: {args}", severity="information")

    def _cmd_task(self, args: str) -> None:
        if not args:
            self.notify("用法: /task <任务描述>", severity="warning")
            return
        self._send_to_manager(f"[新任务] {args}")

    def _cmd_review(self, args: str) -> None:
        self.notify(f"查看审批: {args}", severity="information")

    def _show_system_message(self, text: str) -> None:
        rich_log = self.query_one("#chat-messages", RichLog)
        rich_log.write(
            f"[#f9ca24]│[/] [#f9ca24]🔔 系统[/]\n"
            f"[#f9ca24]│[/]    {text}\n",
            scroll_end=self._auto_scroll,
        )

    # ── 快捷键 ──

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_scroll_top(self) -> None:
        self._auto_scroll = False
        rich_log = self.query_one("#chat-messages", RichLog)
        rich_log.scroll_home(animate=False)

    def action_scroll_bottom(self) -> None:
        self._auto_scroll = True
        rich_log = self.query_one("#chat-messages", RichLog)
        rich_log.scroll_end(animate=False)

    def action_show_status(self) -> None:
        self._cmd_status("")

    def action_show_escalations(self) -> None:
        self._cmd_escalations("")
