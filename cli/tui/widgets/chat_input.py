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
