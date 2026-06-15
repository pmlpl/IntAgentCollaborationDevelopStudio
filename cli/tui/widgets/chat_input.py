"""聊天输入组件和消息渲染。"""
from __future__ import annotations

from datetime import datetime
from core.ipc.message_log import MessageRecord, ChatRole, classify_role


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
    """将一条 MessageRecord 渲染为 Rich markup 字符串。

    返回的字符串可直接传入 RichLog.write()。
    """
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


from dataclasses import dataclass
from textual.widgets import Input
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static


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

    # / 命令补全
    if text.startswith("/"):
        prefix = text[1:].lower()
        for cmd_name in COMMANDS:
            if cmd_name.startswith(prefix) and cmd_name != prefix:
                results.append(f"/{cmd_name}")

    # @ 提及补全
    elif text.startswith("@"):
        prefix = text[1:].lower()
        for agent_id in agent_ids:
            if agent_id.lower().startswith(prefix) and agent_id.lower() != prefix:
                results.append(f"@{agent_id}")

    return results


# ── ChatInput Widget ──

class ChatInput(Input):
    """带补全功能的聊天输入框。"""

    def __init__(self, agent_ids: list[str] | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._agent_ids = agent_ids or []
        self._history: list[str] = []
        self._history_idx: int = -1
        self._completions: list[str] = []
        self._completion_idx: int = -1

    def push_history(self, text: str) -> None:
        """记录一条已发送的消息到历史。"""
        if text and (not self._history or self._history[-1] != text):
            self._history.append(text)
            if len(self._history) > 100:
                self._history = self._history[-100:]
        self._history_idx = -1

    def on_key(self, event) -> None:
        """拦截 Tab / Up / Down 键。"""
        if event.key == "tab":
            self._handle_tab()
            event.prevent_default()
        elif event.key == "up" and self.value == "":
            self._history_prev()
            event.prevent_default()
        elif event.key == "down" and self.value == "":
            self._history_next()
            event.prevent_default()

    def _handle_tab(self) -> None:
        """Tab 补全：循环补全候选。"""
        if not self.value:
            return

        if not self._completions or self._completion_idx == -1:
            self._completions = get_completions(self.value, self._agent_ids)
            if not self._completions:
                return
            self._completion_idx = 0
        else:
            self._completion_idx = (self._completion_idx + 1) % len(self._completions)

        self.value = self._completions[self._completion_idx]

    def _history_prev(self) -> None:
        """上箭头：浏览历史（从新到旧）。"""
        if not self._history:
            return
        if self._history_idx == -1:
            self._history_idx = len(self._history) - 1
        elif self._history_idx > 0:
            self._history_idx -= 1
        self.value = self._history[self._history_idx]

    def _history_next(self) -> None:
        """下箭头：浏览历史（从旧到新）。"""
        if self._history_idx == -1:
            return
        if self._history_idx < len(self._history) - 1:
            self._history_idx += 1
            self.value = self._history[self._history_idx]
        else:
            self._history_idx = -1
            self.value = ""

    def _on_input_changed(self, event) -> None:
        """输入变化时重置补全状态。"""
        self._completions = []
        self._completion_idx = -1
