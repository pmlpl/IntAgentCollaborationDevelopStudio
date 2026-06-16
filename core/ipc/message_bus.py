# core/ipc/message_bus.py — 基于文件的 Agent inbox 消息总线
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import uuid


@dataclass
class Message:
    """Agent 间消息。"""

    id: str
    type: str
    sender: str
    recipient: str
    task_id: str
    payload: dict[str, Any]
    trace: list[str] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @staticmethod
    def new_id() -> str:
        return f"msg-{uuid.uuid4().hex[:12]}"


class MessageBus:
    """文件队列式 inbox。"""

    def __init__(self, inbox_dir: Path):
        self.inbox_dir = inbox_dir
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        (self.inbox_dir / "processed").mkdir(exist_ok=True)

    def _to_json_dict(self, msg: Message) -> dict:
        d = asdict(msg)
        d["from"] = d.pop("sender")
        d["to"] = d.pop("recipient")
        return d

    def _from_json_dict(self, data: dict) -> Message:
        data = dict(data)
        data["sender"] = data.pop("from")
        data["recipient"] = data.pop("to")
        return Message(**data)

    def deliver(self, msg: Message) -> Path:
        path = self.inbox_dir / f"{msg.id}.json"
        path.write_text(
            json.dumps(self._to_json_dict(msg), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def drain(self) -> list[Message]:
        messages: list[Message] = []
        for path in sorted(self.inbox_dir.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            messages.append(self._from_json_dict(data))
            processed = self.inbox_dir / "processed" / path.name
            path.rename(processed)
        return messages

    def peek_count(self) -> int:
        return len(list(self.inbox_dir.glob("*.json")))

    def peek(self) -> list[Message]:
        """读取 inbox 中未消费的消息（不移动文件）。"""
        messages: list[Message] = []
        for path in sorted(self.inbox_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                messages.append(self._from_json_dict(data))
            except (json.JSONDecodeError, KeyError):
                continue
        return messages

    def scan_processed(self, limit: int = 50) -> list[Message]:
        """读取 processed/ 中最近 N 条历史消息，按修改时间排序。"""
        proc_dir = self.inbox_dir / "processed"
        if not proc_dir.exists():
            return []
        files = sorted(
            proc_dir.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:limit]
        messages: list[Message] = []
        for path in files:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                messages.append(self._from_json_dict(data))
            except (json.JSONDecodeError, KeyError):
                continue
        messages.reverse()  # 恢复时间正序
        return messages

    def scan_all(self, limit: int = 50) -> list[Message]:
        """合并 peek() + scan_processed()，按 created_at 排序返回最近 N 条。"""
        pending = self.peek()
        history = self.scan_processed(limit)
        # 去重（pending 消息可能同时出现在两个来源）
        seen: set[str] = set()
        merged: list[Message] = []
        for msg in pending + history:
            if msg.id not in seen:
                seen.add(msg.id)
                merged.append(msg)
        merged.sort(key=lambda m: m.created_at)
        return merged[-limit:]
