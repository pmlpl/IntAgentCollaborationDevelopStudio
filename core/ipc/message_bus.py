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
