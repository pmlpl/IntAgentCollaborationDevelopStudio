"""聊天输入组件和消息渲染。"""
from __future__ import annotations

from datetime import datetime
from dataclasses import dataclass

from textual.widgets import Input, Static, ListView, ListItem, Label
from textual.app import ComposeResult
from textual.containers import Vertical

from core.ipc.message_log import MessageRecord, ChatRole, classify_role


# ── 消息渲染 ──

# 角色 → (图标, 显示名, Rich 颜色, 是否有左边框)
_ROLE_STYLE: dict[ChatRole, tuple[str, str, str, bool]] = {
    ChatRole.CEO:     ("👤", "CEO",    "#ff6b9d", False),
    ChatRole.MANAGER: ("🤖", "Manager", "#4ecdc4", True),
    ChatRole.WORKER:  ("⚡", "Worker",  "#45b7d1", True),
    ChatRole.SYSTEM:  ("🔔", "系统",    "#f9ca24", True),
}


def _format_time(iso_str: str) -> str:
    """ISO 时间字符串 → HH:MM:SS。"""
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%H:%M:%S")
    except (ValueError, TypeError):
        return "??:??:??"


def _extract_text(msg) -> str:
    """从 payload 中提取文本摘要。"""
    payload = msg.payload or {}
    text = payload.get("text", "")
    if not text:
        for key in ("summary", "result", "verdict"):
            if key in payload:
                val = payload[key]
                if isinstance(val, str):
                    text = val
                    break
                elif isinstance(val, dict):
                    text = val.get("text", str(val)[:120])
                    break
    if len(text) > 200:
        text = text[:197] + "..."
    return text


def render_chat_message(rec: MessageRecord) -> str:
    """将一条 MessageRecord 渲染为 Rich markup 字符串。"""
    msg = rec.message
    role = classify_role(msg)
    icon, name, color, has_border = _ROLE_STYLE[role]
    t = _format_time(msg.created_at)
    pending = " [yellow]●[/]" if rec.is_pending else ""
    text = _extract_text(msg)

    header = f"[{color}]{icon} {name}[/] [dim]{t}[/]{pending}"

    if has_border:
        border = f"[{color}]│[/]"
        lines = [f"{border} {header}"]
        if text:
            for line in text.split("\n"):
                lines.append(f"{border}   {line}")
    else:
        lines = [header]
        if text:
            for line in text.split("\n"):
                lines.append(f"   {line}")

    return "\n".join(lines)


# ── Slash 命令定义 ──

COMMANDS: dict[str, str] = {
    "task": "下派新任务给 Manager",
    "review": "查看/审批任务评审结果",
    "status": "显示当前编排进度概览",
    "escalations": "列出所有待 CEO 决策的升级",
    "history": "加载最近 n 条历史消息",
    "filter": "只显示指定 Agent 的消息",
    "clear": "清空当前屏幕（不删数据）",
    "help": "显示所有命令帮助",
}


@dataclass
class SlashCommand:
    """解析后的斜杠命令。"""
    name: str
    args: str


def parse_slash_command(text: str) -> SlashCommand | None:
    """解析用户输入为斜杠命令。如果不是 / 开头则返回 None。"""
    text = text.strip()
    if not text.startswith("/") or len(text) < 2:
        return None
    parts = text[1:].split(maxsplit=1)
    name = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""
    return SlashCommand(name=name, args=args)


def get_completions(
    text: str,
    agent_ids: list[str] | None = None,
) -> list[str]:
    """根据当前输入返回补全候选列表。"""
    text = text.strip()
    if not text:
        return []

    if agent_ids is None:
        agent_ids = []

    results: list[str] = []

    if text.startswith("/"):
        prefix = text[1:].lower()
        for cmd_name in COMMANDS:
            if cmd_name.startswith(prefix) and cmd_name != prefix:
                results.append(f"/{cmd_name}")

    elif text.startswith("@"):
        prefix = text[1:].lower()
        for agent_id in agent_ids:
            if agent_id.lower().startswith(prefix) and agent_id.lower() != prefix:
                results.append(f"@{agent_id}")

    return results


def filter_commands(prefix: str) -> list[tuple[str, str]]:
    """根据前缀过滤命令列表，返回 (命令名, 描述) 对。

    prefix 不含 /，例如 "ta" 匹配 ("task", "下派新任务给 Manager")。
    当 prefix 为空时返回所有命令。
    """
    prefix = prefix.lower()
    return [
        (name, desc)
        for name, desc in COMMANDS.items()
        if name.startswith(prefix)
    ]


# ── 自动补全下拉列表 ──

class CompletionDropdown(ListView):
    """命令自动补全下拉列表。

    输入 / 时弹出，每输入一个字符实时过滤，↑↓ 选择，Enter 确认。
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._commands: list[tuple[str, str]] = []

    def update_items(self, items: list[tuple[str, str]]) -> None:
        """更新列表项。items 为 (命令名, 描述) 对列表。"""
        self._commands = items
        self.clear()
        for name, desc in items:
            item = ListItem(
                Label(f"[bold #f9ca24]/{name}[/]  [dim]{desc}[/]"),
                name=f"cmd-{name}",
            )
            self.append(item)
        # 自动选中第一项
        if items:
            self.index = 0

    def get_selected_command(self) -> str | None:
        """获取当前选中的命令名（不含 /）。"""
        if self._commands and 0 <= self.index < len(self._commands):
            return self._commands[self.index][0]
        return None


# ── ChatInput 区域（输入框 + 下拉） ──

class ChatInputArea(Vertical):
    """聊天输入区域：包含自动补全下拉和输入框。"""

    def __init__(self, agent_ids: list[str] | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._agent_ids = agent_ids or []
        self._history: list[str] = []
        self._history_idx: int = -1
        self._dropdown_visible: bool = False
        self._suppress_changed: bool = False  # 防止程序改值时触发过滤

    def compose(self) -> ComposeResult:
        yield CompletionDropdown(id="chat-completion")
        yield Input(
            placeholder="输入指令… /:命令 ↑↓:选择 Enter:发送",
            id="chat-input",
        )

    def on_mount(self) -> None:
        """初始状态下拉隐藏。"""
        dropdown = self.query_one("#chat-completion", CompletionDropdown)
        dropdown.display = False

    # ── 输入事件 ──

    def _on_input_changed(self, event: Input.Changed) -> None:
        """每次输入变化时实时更新下拉列表。"""
        if self._suppress_changed:
            return

        text = event.value
        dropdown = self.query_one("#chat-completion", CompletionDropdown)

        if text.startswith("/"):
            # 提取 / 后面的前缀
            prefix = text[1:].split(maxsplit=1)[0] if len(text) > 1 else ""
            items = filter_commands(prefix)
            if items:
                dropdown.update_items(items)
                dropdown.display = True
                self._dropdown_visible = True
            else:
                dropdown.display = False
                self._dropdown_visible = False
        elif text.startswith("@"):
            prefix = text[1:].lower()
            matches = [
                (aid, "Agent")
                for aid in self._agent_ids
                if aid.lower().startswith(prefix)
            ]
            if matches:
                dropdown.update_items(matches)
                dropdown.display = True
                self._dropdown_visible = True
            else:
                dropdown.display = False
                self._dropdown_visible = False
        else:
            dropdown.display = False
            self._dropdown_visible = False

    # ── 键盘事件 ──

    def on_key(self, event) -> None:
        """拦截特殊按键。"""
        dropdown = self.query_one("#chat-completion", CompletionDropdown)

        if event.key == "tab" and self._dropdown_visible:
            # Tab 在下拉中选中当前项并填入
            self._accept_completion()
            event.prevent_default()

        elif event.key == "enter":
            if self._dropdown_visible:
                # 下拉打开时 Enter 选中当前项并关闭
                self._accept_completion()
                event.prevent_default()
            else:
                # 下拉关闭时 Enter 正常提交
                # 由 Input.Submitted 事件处理，不拦截
                pass

        elif event.key == "escape" and self._dropdown_visible:
            # Escape 关闭下拉
            dropdown.display = False
            self._dropdown_visible = False
            event.prevent_default()

        elif event.key == "up":
            if self._dropdown_visible:
                # 下拉中 ↑ 选择上一项
                event.prevent_default()
                if dropdown.index > 0:
                    dropdown.index -= 1
            elif self.query_one("#chat-input", Input).value == "":
                # 输入为空时 ↑ 浏览历史
                self._history_prev()
                event.prevent_default()

        elif event.key == "down":
            if self._dropdown_visible:
                # 下拉中 ↓ 选择下一项
                event.prevent_default()
                if dropdown.index < len(dropdown._commands) - 1:
                    dropdown.index += 1
            elif self.query_one("#chat-input", Input).value == "":
                self._history_next()
                event.prevent_default()

    def _accept_completion(self) -> None:
        """将选中的补全项填入输入框。"""
        dropdown = self.query_one("#chat-completion", CompletionDropdown)
        cmd = dropdown.get_selected_command()
        if cmd:
            self._suppress_changed = True
            input_widget = self.query_one("#chat-input", Input)
            input_widget.value = f"/{cmd} "
            input_widget.cursor_position = len(input_widget.value)
            self._suppress_changed = False

        dropdown.display = False
        self._dropdown_visible = False
        # 重新聚焦输入框
        self.query_one("#chat-input", Input).focus()

    # ── 历史浏览 ──

    def push_history(self, text: str) -> None:
        """记录一条已发送的消息到历史。"""
        if text and (not self._history or self._history[-1] != text):
            self._history.append(text)
            if len(self._history) > 100:
                self._history = self._history[-100:]
        self._history_idx = -1

    def clear_input(self) -> None:
        """清空输入框。"""
        self._suppress_changed = True
        self.query_one("#chat-input", Input).value = ""
        self._suppress_changed = False
        # 隐藏下拉
        dropdown = self.query_one("#chat-completion", CompletionDropdown)
        dropdown.display = False
        self._dropdown_visible = False

    def _history_prev(self) -> None:
        """上箭头：浏览历史（从新到旧）。"""
        if not self._history:
            return
        if self._history_idx == -1:
            self._history_idx = len(self._history) - 1
        elif self._history_idx > 0:
            self._history_idx -= 1
        self._suppress_changed = True
        self.query_one("#chat-input", Input).value = self._history[self._history_idx]
        self._suppress_changed = False

    def _history_next(self) -> None:
        """下箭头：浏览历史（从旧到新）。"""
        if self._history_idx == -1:
            return
        self._suppress_changed = True
        if self._history_idx < len(self._history) - 1:
            self._history_idx += 1
            self.query_one("#chat-input", Input).value = self._history[self._history_idx]
        else:
            self._history_idx = -1
            self.query_one("#chat-input", Input).value = ""
        self._suppress_changed = False
