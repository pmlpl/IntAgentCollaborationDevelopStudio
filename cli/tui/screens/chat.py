"""主管聊天频道 — CEO ↔ Manager 全场景对话界面。"""
from __future__ import annotations

import re
from pathlib import Path

from rich.markup import render as rich_render
from textual.app import ComposeResult
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

# ── 工具函数 ──

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\].*?\x07")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

AVAILABLE_MODELS = {
    "claude": "Claude (Anthropic)",
    "gpt": "GPT (OpenAI)",
    "deepseek": "DeepSeek",
    "gemini": "Gemini (Google)",
}

_THINKING_FRAMES = [
    "[#4ecdc4]◐[/] 主管正在思考",
    "[#4ecdc4]◓[/] 主管正在思考.",
    "[#4ecdc4]◑[/] 主管正在思考..",
    "[#4ecdc4]◒[/] 主管正在思考...",
]


def _w(log: RichLog, markup: str, **kw) -> None:
    """写入 Rich markup 到 RichLog。"""
    log.write(rich_render(markup), **kw)


def _strip_ansi(text: str) -> str:
    """去除 ANSI 转义码和控制字符。"""
    text = _ANSI_RE.sub("", text)
    text = _CONTROL_RE.sub("", text)
    return text.strip()


def _build_agent_prompt(ceo_text: str, history: list[str] | None = None) -> str:
    """构建发给 Manager Agent 的 prompt。"""
    parts = [
        "你是项目的主管（Manager），CEO 在和你直接对话。",
        "请用中文简洁回复。如果 CEO 提的是任务需求，给出你的分析和建议。",
        "如果需要更多信息，提出你的问题。",
        "",
    ]
    if history:
        parts.append("最近对话：")
        for h in history[-6:]:
            parts.append(f"  {h}")
        parts.append("")
    parts.append(f"CEO 说：{ceo_text}")
    return "\n".join(parts)


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
        self._model: str = "claude"
        self._recent_history: list[str] = []
        # 本地已渲染的消息 ID（防止轮询重复渲染）
        self._rendered_ids: set[str] = set()

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
        model_name = AVAILABLE_MODELS.get(self._model, self._model)
        parts.append(f"模型: {model_name}")
        parts.append("esc:返回")
        return " │ ".join(parts)

    def _agent_ids(self) -> list[str]:
        if not self._project_dir:
            return []
        agents_dir = self._project_dir / "agents"
        if not agents_dir.exists():
            return []
        return sorted(d.name for d in agents_dir.iterdir() if d.is_dir())

    # ── 生命周期 ──

    def on_mount(self) -> None:
        self._sync_context()
        input_area = self.query_one("#chat-input-area", ChatInputArea)
        input_area._agent_ids = self._agent_ids()
        if self._project_dir:
            self._collector = MessageLogCollector(self._project_dir)
            self._load_history()
        self.set_interval(2.0, self._poll_messages)

    def _sync_context(self) -> None:
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
        if not self._collector:
            return
        records = self._collector.collect_new(limit_per_agent=15)
        if not records:
            return
        # 标记历史消息为已渲染（防止轮询重复）
        for rec in records:
            self._rendered_ids.add(rec.message.id)
        recent = records[-30:]
        log = self.query_one("#chat-messages", RichLog)
        _w(log, "[dim]── 会话开始 ──[/]", scroll_end=False)
        for rec in recent:
            _w(log, render_chat_message(rec), scroll_end=False)

    # ── 轮询 ──

    def _poll_messages(self) -> None:
        if not self._collector:
            return
        new_records = self._collector.collect_new()
        has_new = False
        for rec in new_records:
            # 跳过本地已渲染的消息
            if rec.message.id in self._rendered_ids:
                continue
            self._rendered_ids.add(rec.message.id)
            # 清理 ANSI（外部 Agent 可能带脏输出）
            msg = rec.message
            if msg.payload and isinstance(msg.payload.get("text"), str):
                msg.payload["text"] = _strip_ansi(msg.payload["text"])
            has_new = True
            log = self.query_one("#chat-messages", RichLog)
            _w(log, render_chat_message(rec), scroll_end=self._auto_scroll)
        if has_new and self._is_thinking:
            self._stop_thinking()
        self._check_task_state()

    def _check_task_state(self) -> None:
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
                    log = self.query_one("#chat-messages", RichLog)
                    _w(log, f"[#f9ca24]│[/] [#f9ca24]🔔 系统[/]\n"
                            f"[#f9ca24]│[/]    任务 {self._task_id} 状态变更: {state}",
                       scroll_end=self._auto_scroll)
        except Exception:
            pass

    # ── 思考动画 ──

    def _start_thinking(self) -> None:
        self._is_thinking = True
        self._think_frame = 0
        self._update_think_frame()
        self._think_timer = self.set_interval(0.4, self._update_think_frame)

    def _update_think_frame(self) -> None:
        status = self.query_one("#chat-status", Static)
        status.update(rich_render(_THINKING_FRAMES[self._think_frame % len(_THINKING_FRAMES)]))
        self._think_frame += 1

    def _stop_thinking(self) -> None:
        self._is_thinking = False
        if self._think_timer:
            self._think_timer.stop()
            self._think_timer = None
        status = self.query_one("#chat-status", Static)
        status.update("")

    # ── 发送消息 ──

    def on_input_submitted(self, event) -> None:
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
        if not self._project_dir or not self._manager_id:
            self.notify("未连接到项目或 Manager", severity="warning")
            return

        # 投递到 Manager inbox（系统记录用，不在聊天中渲染）
        msg = send_ceo_feedback(
            project_dir=self._project_dir,
            manager_id=self._manager_id,
            text=text,
            task_id=self._task_id,
        )
        # 标记为已渲染（防止轮询捡到后重复显示）
        self._rendered_ids.add(msg.id)

        # 本地立即显示 CEO 消息
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).strftime("%H:%M:%S")
        log = self.query_one("#chat-messages", RichLog)
        _w(log, f"[#ff6b9d]👤 CEO[/] [dim]{now}[/]\n   {text}",
           scroll_end=self._auto_scroll)
        self._recent_history.append(f"CEO: {text}")

        # 思考 + 异步调用 Agent
        self._start_thinking()
        self._ask_manager_agent(text)

    @work(thread=True, exclusive=True)
    def _ask_manager_agent(self, text: str) -> None:
        """后台线程调用 Manager Agent。"""
        try:
            from core.project import get_studio_root
            root = get_studio_root()
            from agents.runner import load_position, run_agent_prompt_capture
            pos = load_position(self._project_dir, self._manager_id)
            agent_key = pos.get("agent", "claude")

            prompt = _build_agent_prompt(text, self._recent_history)

            rc, output = run_agent_prompt_capture(
                root=root,
                agent_key=agent_key,
                prompt=prompt,
                cwd=self._project_dir,
                timeout_sec=120,
            )

            output = _strip_ansi(output)
            self.app.call_from_thread(self._on_manager_reply, rc, output)
        except Exception as exc:
            self.app.call_from_thread(self._on_manager_error, _strip_ansi(str(exc)))

    def _on_manager_reply(self, rc: int, output: str) -> None:
        self._stop_thinking()
        log = self.query_one("#chat-messages", RichLog)
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).strftime("%H:%M:%S")

        if rc == 0 and output.strip():
            reply = output.strip()
            if len(reply) > 2000:
                reply = reply[:1997] + "..."
            self._recent_history.append(f"Manager: {reply}")

            _w(log, f"[#4ecdc4]│[/] [#4ecdc4]🤖 {self._manager_id}[/] [dim]{now}[/] [#4ecdc4]({AVAILABLE_MODELS.get(self._model, self._model)})[/]")
            for line in reply.split("\n"):
                _w(log, f"[#4ecdc4]│[/]   {line}")
            _w(log, "", scroll_end=self._auto_scroll)
        else:
            error_msg = output if output else "Agent 无输出"
            _w(log, f"[#4ecdc4]│[/] [#4ecdc4]🤖 {self._manager_id}[/] [dim]{now}[/]\n"
                     f"[#4ecdc4]│[/]   [red]回复失败: {error_msg}[/]",
               scroll_end=self._auto_scroll)

    def _on_manager_error(self, error: str) -> None:
        self._stop_thinking()
        log = self.query_one("#chat-messages", RichLog)
        _w(log, f"[red]│[/] [red]⚠ 错误[/]\n"
                 f"[red]│[/]   Agent 调用失败: {error}",
           scroll_end=self._auto_scroll)

    # ── 斜杠命令 ──

    def _handle_slash_command(self, cmd: SlashCommand) -> None:
        handler = getattr(self, f"_cmd_{cmd.name}", None)
        if handler:
            handler(cmd.args)
        else:
            self.notify(f"未知命令: /{cmd.name}", severity="warning")

    def _cmd_status(self, args: str) -> None:
        self._show_system_message("正在获取状态…")

    def _cmd_escalations(self, args: str) -> None:
        self._show_system_message("查看待决策升级…")

    def _cmd_clear(self, args: str) -> None:
        log = self.query_one("#chat-messages", RichLog)
        log.clear()
        self._rendered_ids.clear()
        _w(log, "[dim]── 屏幕已清空 ──[/]")

    def _cmd_help(self, args: str) -> None:
        log = self.query_one("#chat-messages", RichLog)
        _w(log, "[#f9ca24]│[/] [#f9ca24]🔔 命令帮助[/]")
        for name, desc in COMMANDS.items():
            _w(log, f"[#f9ca24]│[/]   [bold]/{name}[/] — {desc}")
        _w(log, "", scroll_end=self._auto_scroll)

    def _cmd_history(self, args: str) -> None:
        try:
            n = int(args) if args else 30
        except ValueError:
            n = 30
        if not self._collector:
            return
        self._collector.reset()
        records = self._collector.collect_new(limit_per_agent=n)
        for rec in records:
            self._rendered_ids.add(rec.message.id)
        recent = records[-n:]
        log = self.query_one("#chat-messages", RichLog)
        for rec in recent:
            _w(log, render_chat_message(rec), scroll_end=False)
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

    def _cmd_model(self, args: str) -> None:
        if args == "list" or not args:
            log = self.query_one("#chat-messages", RichLog)
            _w(log, "[#f9ca24]│[/] [#f9ca24]🔔 可用模型[/]")
            for key, name in AVAILABLE_MODELS.items():
                marker = " ▸ 当前" if key == self._model else ""
                _w(log, f"[#f9ca24]│[/]   [bold]{key}[/] — {name}[cyan]{marker}[/]")
            _w(log, f"[#f9ca24]│[/]   用法: /model <名称>", scroll_end=self._auto_scroll)
            return
        model_key = args.strip().lower()
        if model_key not in AVAILABLE_MODELS:
            self.notify(f"未知模型: {model_key}，可用: {', '.join(AVAILABLE_MODELS)}", severity="warning")
            return
        self._model = model_key
        model_name = AVAILABLE_MODELS[model_key]
        self._show_system_message(f"已切换模型: {model_name}")
        self.query_one("#chat-header", Static).update(self._build_header_text())
        self.notify(f"模型已切换为 {model_name}", severity="information")

    def _show_system_message(self, text: str) -> None:
        log = self.query_one("#chat-messages", RichLog)
        _w(log, f"[#f9ca24]│[/] [#f9ca24]🔔 系统[/]\n"
                 f"[#f9ca24]│[/]    {text}",
           scroll_end=self._auto_scroll)

    # ── 快捷键 ──

    def action_back(self) -> None:
        self._stop_thinking()
        self.app.pop_screen()

    def action_scroll_top(self) -> None:
        self._auto_scroll = False
        self.query_one("#chat-messages", RichLog).scroll_home(animate=False)

    def action_scroll_bottom(self) -> None:
        self._auto_scroll = True
        self.query_one("#chat-messages", RichLog).scroll_end(animate=False)

    def action_show_status(self) -> None:
        self._cmd_status("")

    def action_show_escalations(self) -> None:
        self._cmd_escalations("")
