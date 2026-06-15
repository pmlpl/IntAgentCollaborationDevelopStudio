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
from cli.tui.widgets.model_config import ModelConfigBar
from core.dispatch.dispatcher import Dispatcher, get_dispatcher
from core.ipc.ceo_chat import send_ceo_feedback
from core.ipc.message_log import MessageLogCollector

# ── 工具函数 ──

_ANSI_RE = re.compile(
    r"""
    \x1b(?:                        # ESC 序列
        \[[\d;?]*[a-zA-Z]          # CSI: \x1b[...X（含 ? 私有模式如 ?25l）
        | \][^\x07]*\x07           # OSC: \x1b]...\x07
        | [()][A-Z0-9]             # 字符集切换
        | [=#<>]                   # DEC 序列
        | [A-HJM-Z]                # 单字符 ESC 序列
        | .                        # fallback
    )
    """,
    re.VERBOSE | re.DOTALL,
)
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
    text = text.replace("\r", "")
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
        ("m", "toggle_model_config", "模型"),
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
        # Agent 回复期间暂停轮询渲染（防止外部 Agent CLI 往 inbox 写消息导致重复）
        self._pause_poll: bool = False
        # 编排状态
        self._orch_task_id: str | None = None
        self._orch_root: Path | None = None
        self._orch_disp: Dispatcher | None = None

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
        yield ModelConfigBar(id="model-config-bar")
        yield Footer()

    def _build_header_text(self) -> str:
        parts = ["📡 主管频道"]
        if self._manager_id:
            parts.append(f"Manager: {self._manager_id}")
        if self._task_id:
            parts.append(f"任务: {self._task_id}")
        try:
            bar = self.query_one("#model-config-bar", ModelConfigBar)
            current_model = bar.get_current_model()
        except Exception:
            current_model = self._model
        model_name = AVAILABLE_MODELS.get(current_model, current_model)
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
        self.set_interval(3.0, self._poll_orchestration)

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
        # Agent 回复期间跳过渲染（防止 CLI Agent 写 inbox 导致重复）
        if self._pause_poll:
            return
        has_new = False
        for rec in new_records:
            if rec.message.id in self._rendered_ids:
                continue
            self._rendered_ids.add(rec.message.id)
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
        self._pause_poll = True  # 暂停轮询渲染，防止 CLI Agent 写 inbox 重复
        self._last_ceo_text = text  # 保存原始消息供编排使用
        self._ask_manager_agent(text)

    @work(thread=True, exclusive=True)
    def _ask_manager_agent(self, text: str) -> None:
        """后台线程调用内置 Agent API。"""
        try:
            from agents.chat_agent import build_chat_system_prompt, chat_agent_respond

            bar = self.query_one("#model-config-bar", ModelConfigBar)
            config = bar.build_agent_config()
            # 注入公司组织和项目上下文
            config.system_prompt = build_chat_system_prompt(self._project_dir)

            # 构建历史消息
            history: list[dict[str, str]] = []
            for h in self._recent_history[-6:]:
                if h.startswith("CEO:"):
                    history.append({"role": "user", "content": h[5:]})
                elif h.startswith("Manager:"):
                    history.append({"role": "assistant", "content": h[9:]})

            reply = chat_agent_respond(config, text, history)
            self.app.call_from_thread(self._on_manager_reply, reply)
        except Exception as exc:
            self.app.call_from_thread(self._on_manager_error, str(exc))

    def _on_manager_reply(self, reply: str) -> None:
        self._stop_thinking()
        self._pause_poll = False
        log = self.query_one("#chat-messages", RichLog)
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).strftime("%H:%M:%S")

        if reply.strip():
            if len(reply) > 2000:
                reply = reply[:1997] + "..."
            self._recent_history.append(f"Manager: {reply}")

            bar = self.query_one("#model-config-bar", ModelConfigBar)
            model_name = AVAILABLE_MODELS.get(bar.get_current_model(), bar.get_current_model())
            _w(log, f"[#4ecdc4]│[/] [#4ecdc4]🤖 {self._manager_id}[/] [dim]{now}[/] [#4ecdc4]({model_name})[/]")
            for line in reply.split("\n"):
                _w(log, f"[#4ecdc4]│[/]   {line}")
            _w(log, "", scroll_end=self._auto_scroll)
        else:
            _w(log, f"[#4ecdc4]│[/] [#4ecdc4]🤖 {self._manager_id}[/] [dim]{now}[/]\n"
                     f"[#4ecdc4]│[/]   [dim]（无回复内容）[/]",
               scroll_end=self._auto_scroll)

        # Agent 回复完成后，自动触发编排（如果有项目连接）
        if self._project_dir and self._manager_id:
            self._start_orchestration(self._last_ceo_text)

    def _on_manager_error(self, error: str) -> None:
        self._stop_thinking()
        self._pause_poll = False
        log = self.query_one("#chat-messages", RichLog)
        _w(log, f"[red]│[/] [red]⚠ 错误[/]\n"
                 f"[red]│[/]   {error}",
           scroll_end=self._auto_scroll)

    # ── 自动编排 ──

    def _start_orchestration(self, description: str) -> None:
        """触发自动编排流程。"""
        if not self._project_dir:
            return
        try:
            from core.project import get_studio_root
            root = get_studio_root()
            project_name = getattr(self.app, "project_name", None)
            if not project_name:
                return
            disp = get_dispatcher(root, project_name)
            task = disp.begin_orchestration(root, description, spawn_terminals=True)
            self._orch_task_id = task["id"]
            self._orch_root = root
            self._orch_disp = disp

            log = self.query_one("#chat-messages", RichLog)
            _w(log, f"[#f9ca24]│[/] [#f9ca24]🔔 编排启动[/]\n"
                    f"[#f9ca24]│[/]    任务 {task['id']} 已创建，主管正在拆解…",
               scroll_end=self._auto_scroll)
        except Exception as exc:
            log = self.query_one("#chat-messages", RichLog)
            _w(log, f"[red]│[/] [red]⚠ 编排启动失败[/]\n"
                    f"[red]│[/]   {exc}",
               scroll_end=self._auto_scroll)

    def _poll_orchestration(self) -> None:
        """轮询编排进度。"""
        if not self._orch_task_id or not self._orch_root or not self._orch_disp:
            return
        try:
            disp = self._orch_disp
            root = self._orch_root

            progressed = disp.try_complete_orchestration(
                root, self._orch_task_id, spawn_terminals=True
            )
            if progressed:
                # 查找根任务状态
                for t in disp.get_status():
                    if t.get("id") == self._orch_task_id:
                        state = t.get("status", "")
                        log = self.query_one("#chat-messages", RichLog)
                        if state == "assigned":
                            _w(log, f"[#4ecdc4]│[/] [#4ecdc4]🤖 编排进度[/]\n"
                                    f"[#4ecdc4]│[/]    任务已拆解并分配，Worker 终端已弹出",
                               scroll_end=self._auto_scroll)
                        elif state in ("in_review",):
                            _w(log, f"[#f9ca24]│[/] [#f9ca24]🤖 编排进度[/]\n"
                                    f"[#f9ca24]│[/]    Worker 已交付，主管审查中…",
                               scroll_end=self._auto_scroll)
                        elif state in ("approved", "archived"):
                            _w(log, f"[#3fb950]│[/] [#3fb950]✅ 任务完成[/]\n"
                                    f"[#3fb950]│[/]    状态: {state}",
                               scroll_end=self._auto_scroll)
                            self._orch_task_id = None
                            self._orch_root = None
                            self._orch_disp = None
                        break

            # 持续检查交付和审查
            disp.poll_deliveries(root)
            disp.try_run_manager_reviews(root)

        except Exception:
            pass

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
        bar = self.query_one("#model-config-bar", ModelConfigBar)
        bar._model = model_key
        bar._update_summary()
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

    def action_toggle_model_config(self) -> None:
        """切换模型配置栏展开/折叠。"""
        bar = self.query_one("#model-config-bar", ModelConfigBar)
        bar.toggle()
