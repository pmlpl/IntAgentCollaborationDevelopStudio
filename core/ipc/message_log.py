# core/ipc/message_log.py — 跨 Agent inbox 的消息日志收集器
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from core.ipc.message_bus import Message, MessageBus


class ChatRole(Enum):
    """聊天消息的角色分类。"""
    CEO = "ceo"
    MANAGER = "manager"
    WORKER = "worker"
    SYSTEM = "system"


# 消息类型 → 角色映射
_TYPE_ROLE_MAP: dict[str, ChatRole] = {
    "ceo_feedback": ChatRole.CEO,
    "ceo_review": ChatRole.CEO,
    "task_decompose": ChatRole.MANAGER,
    "reply": ChatRole.MANAGER,
    "delivery": ChatRole.WORKER,
    "review_request": ChatRole.WORKER,
    "escalation": ChatRole.WORKER,
}


def classify_role(msg: Message) -> ChatRole:
    """根据消息类型和发送者判断角色。"""
    if msg.type in _TYPE_ROLE_MAP:
        return _TYPE_ROLE_MAP[msg.type]
    # 回退：根据 sender 前缀猜测
    if msg.sender.startswith("worker") or msg.sender.startswith("wrk"):
        return ChatRole.WORKER
    if msg.sender.startswith("manager") or msg.sender.startswith("mgr"):
        return ChatRole.MANAGER
    return ChatRole.SYSTEM


@dataclass
class MessageRecord:
    """带显示元数据的消息记录。"""

    message: Message
    inbox_owner: str   # 消息所在的 agent inbox 归属（position_id）
    is_pending: bool   # 是否尚未被 drain


class MessageLogCollector:
    """聚合项目下所有 Agent inbox 的消息，用于 TUI 通信中枢面板。

    每次 collect_new() 只返回本轮新发现的消息（通过 _seen_ids 去重）。
    """

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        self._seen_ids: set[str] = set()

    def reset(self) -> None:
        """重置已见 ID 集合（切换编排任务时调用）。"""
        self._seen_ids.clear()

    def collect_new(self, limit_per_agent: int = 20) -> list[MessageRecord]:
        """扫描所有 agent inbox（pending + processed），返回本轮新增消息。"""
        agents_dir = self.project_dir / "agents"
        if not agents_dir.exists():
            return []

        records: list[MessageRecord] = []
        for inbox_dir in sorted(agents_dir.glob("*/inbox")):
            agent_id = inbox_dir.parent.name
            bus = MessageBus(inbox_dir)
            # pending 消息
            for msg in bus.peek():
                if msg.id not in self._seen_ids:
                    self._seen_ids.add(msg.id)
                    records.append(MessageRecord(
                        message=msg,
                        inbox_owner=agent_id,
                        is_pending=True,
                    ))
            # processed 历史
            for msg in bus.scan_processed(limit=limit_per_agent):
                if msg.id not in self._seen_ids:
                    self._seen_ids.add(msg.id)
                    records.append(MessageRecord(
                        message=msg,
                        inbox_owner=agent_id,
                        is_pending=False,
                    ))

        records.sort(key=lambda r: r.message.created_at)
        return records
