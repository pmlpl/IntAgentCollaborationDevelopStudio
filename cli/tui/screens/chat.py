"""主管聊天频道 — CEO ↔ Manager 全场景对话界面。"""
from __future__ import annotations

import threading
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, RichLog, Static
from textual import work

from cli.tui.widgets.chat_input import (
    ChatInputArea,
    SlashCommand,
    render_chat_message,
    parse_slash_command,
    COMMANDS,
)
from core.dispatch.dispatcher import get_dispatcher
from core.ipc.ceo_chat import send_ceo_feedback
from core.ipc.message_log import MessageLogCollector

# 思考动画帧（每 0.4s 切换一帧）
_THINKING_FRAMES = [
    "[#4ecdc4]◐[/] 主管正在思考",
    "[#4ecdc4]◓[/] 主管正在思考.",
    "[#4ecdc4]◑[/] 主管正在思考..",
    "[#4ecdc4]◒[/] 主管正在思考...",
]


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
        self._is_thinking: bool = False
        self._think_frame: int = 0
        self._think_timer = None

    # ── 布局 ──

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(self._build_header_text(), id="chat-header")
        yield RichLog(id="chat-messages", wrap=True, highlight=True)
        yield Static("", id="chat-status")
        yield ChatInputArea(
            agent_ids=self._agent_ids(),
            id="chat-input-area",
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
        input_area = self.query_one("#chat-input-area", ChatInputArea)
        input_area._agent_ids = self._agent_ids()
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
            # 如果有新消息且正在思考，停止思考动画
            if self._is_thinking:
                self._stop_thinking()
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

    # ── 思考动画 ──

    def _start_thinking(self) -> None:
        """启动思考动画。"""
        self._is_thinking = True
        self._think_frame = 0
        # 在状态栏显示动画
        self._update_think_frame()
        self._think_timer = self.set_interval(0.4, self._update_think_frame)

    def _update_think_frame(self) -> None:
        """更新思考动画帧。"""
        status = self.query_one("#chat-status", Static)
        status.update(_THINKING_FRAMES[self._think_frame % len(_THINKING_FRAMES)])
        self._think_frame += 1

    def _stop_thinking(self) -> None:
        """停止思考动画。"""
        self._is_thinking = False
        if self._think_timer:
            self._think_timer.stop()
            self._think_timer = None
        status = self.query_one("#chat-status", Static)
        status.update("")

    # ── 发送消息 ──

    def on_input_submitted(self, event) -> None:
        """处理输入提交。"""
        if event.input.id != "chat-input":
            return
        text = event.value.strip()
        if not text:
            return

        input_area = self.query_one("#chat-input-area", ChatInputArea)
        input_area.push_history(text)

        cmd = parse_slash_command(text)
        if cmd:
            self._handle_slash_command(cmd)
        else:
            self._send_to_manager(text)

        input_area.clear_input()

    def _send_to_manager(self, text: str) -> None:
        """发送自然语言消息给 Manager。"""
        if not self._project_dir or not self._manager_id:
            self.notify("未连接到项目或 Manager", severity="warning")
            return

        # 1. 投递消息到 Manager inbox
        send_ceo_feedback(
            project_dir=self._project_dir,
            manager_id=self._manager_id,
            text=text,
            task_id=self._task_id,
        )

        # 2. 在消息流中立即显示 CEO 消息
        rich_log = self.query_one("#chat-messages", RichLog)
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).strftime("%H:%M:%S")
        rich_log.write(
            f"[#ff6b9d]👤 CEO[/] [dim]{now}[/]\n"
            f"   {text}\n",
            scroll_end=self._auto_scroll,
        )

        # 3. 启动思考动画 + 异步调用 Manager Agent
        self._start_thinking()
        self._ask_manager_agent(text)

    @work(thread=True, exclusive=True)
    def _ask_manager_agent(self, text: str) -> None:
        """在后台线程中调用 Manager Agent 处理消息。"""
        try:
            from core.project import get_studio_root
            root = get_studio_root()

            # 构建 prompt：告知 Agent 它收到 CEO 的消息
            prompt = (
                f"你是主管 Agent，CEO 给你发了一条消息，请回复。\n"
                f"CEO 说：{text}\n\n"
                f"请用中文简洁回复。如果 CEO 提的是任务需求，给出你的分析和建议。"
                f"如果需要更多信息，提出你的问题。"
            )

            # 获取 Manager 的 agent key
            from agents.runner import load_position, run_agent_prompt_capture
            pos = load_position(self._project_dir, self._manager_id)
            agent_key = pos.get("agent", "claude")

            # 调用 Agent（headless 捕获模式）
            rc, output = run_agent_prompt_capture(
                root=root,
                agent_key=agent_key,
                prompt=prompt,
                cwd=self._project_dir,
                timeout_sec=120,
            )

            # 回到 UI 线程渲染回复
            self.app.call_from_thread(
                self._on_manager_reply, rc, output
            )

        except Exception as exc:
            self.app.call_from_thread(
                self._on_manager_error, str(exc)
            )

    def _on_manager_reply(self, rc: int, output: str) -> None:
        """Manager Agent 回复后，渲染到消息流。"""
        self._stop_thinking()
        rich_log = self.query_one("#chat-messages", RichLog)

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).strftime("%H:%M:%S")

        if rc == 0 and output.strip():
            # 清理 Agent 输出（去除多余的前缀/后缀）
            reply = output.strip()
            if len(reply) > 2000:
                reply = reply[:1997] + "..."

            # 投递回复到 CEO inbox（供其他地方也能看到）
            from core.ipc.message_bus import Message, MessageBus
            ceo_inbox = self._project_dir / "agents" / "__ceo__" / "inbox"
            if ceo_inbox.parent.exists():
                bus = MessageBus(ceo_inbox)
                msg = Message(
                    id=Message.new_id(),
                    type="reply",
                    sender=self._manager_id,
                    recipient="__ceo__",
                    task_id=self._task_id,
                    payload={"text": reply},
                    trace=["manager", "chat"],
                )
                bus.deliver(msg)

            rich_log.write(
                f"[#4ecdc4]│[/] [#4ecdc4]🤖 Manager[/] [dim]{now}[/]\n",
                scroll_end=False,
            )
            for line in reply.split("\n"):
                rich_log.write(
                    f"[#4ecdc4]│[/]   {line}",
                    scroll_end=False,
                )
            rich_log.write("", scroll_end=self._auto_scroll)
        else:
            error_msg = output.strip() if output else "Agent 无输出"
            rich_log.write(
                f"[#4ecdc4]│[/] [#4ecdc4]🤖 Manager[/] [dim]{now}[/]\n"
                f"[#4ecdc4]│[/]   [red]回复失败: {error_msg}[/]\n",
                scroll_end=self._auto_scroll,
            )

    def _on_manager_error(self, error: str) -> None:
        """Manager Agent 调用出错。"""
        self._stop_thinking()
        rich_log = self.query_one("#chat-messages", RichLog)
        rich_log.write(
            f"[red]│[/] [red]⚠ 错误[/]\n"
            f"[red]│[/]   Agent 调用失败: {error}\n",
            scroll_end=self._auto_scroll,
        )

    # ── 斜杠命令 ──

    def _handle_slash_command(self, cmd: SlashCommand) -> None:
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
        self._stop_thinking()
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
