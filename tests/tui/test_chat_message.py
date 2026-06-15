"""Tests for chat message rendering and role classification."""
from __future__ import annotations

from core.ipc.message_bus import Message
from core.ipc.message_log import MessageRecord, classify_role, ChatRole
from cli.tui.widgets.chat_input import render_chat_message


def _make_message(msg_type: str, sender: str = "manager-1", recipient: str = "__ceo__") -> Message:
    return Message(
        id=f"test-{msg_type}",
        type=msg_type,
        sender=sender,
        recipient=recipient,
        task_id="T-001",
        payload={"text": "test payload"},
    )


class TestClassifyRole:
    def test_ceo_feedback_is_ceo(self):
        msg = _make_message("ceo_feedback", sender="__ceo__")
        assert classify_role(msg) == ChatRole.CEO

    def test_ceo_review_is_ceo(self):
        msg = _make_message("ceo_review", sender="__ceo__")
        assert classify_role(msg) == ChatRole.CEO

    def test_task_decompose_is_manager(self):
        msg = _make_message("task_decompose")
        assert classify_role(msg) == ChatRole.MANAGER

    def test_delivery_is_worker(self):
        msg = _make_message("delivery", sender="worker-1")
        assert classify_role(msg) == ChatRole.WORKER

    def test_review_request_is_worker(self):
        msg = _make_message("review_request", sender="worker-1")
        assert classify_role(msg) == ChatRole.WORKER

    def test_escalation_is_worker(self):
        msg = _make_message("escalation", sender="worker-1")
        assert classify_role(msg) == ChatRole.WORKER

    def test_unknown_type_falls_back_by_sender(self):
        msg = _make_message("unknown_type", sender="worker-1")
        assert classify_role(msg) == ChatRole.WORKER

    def test_unknown_sender_defaults_to_system(self):
        msg = _make_message("unknown_type", sender="ghost-agent")
        assert classify_role(msg) == ChatRole.SYSTEM


class TestRenderChatMessage:
    def test_ceo_message_has_pink_color(self):
        msg = _make_message("ceo_feedback", sender="__ceo__")
        rec = MessageRecord(message=msg, inbox_owner="__ceo__", is_pending=False)
        result = render_chat_message(rec)
        assert "#ff6b9d" in result
        assert "👤" in result
        assert "CEO" in result

    def test_manager_message_has_teal_border(self):
        msg = _make_message("task_decompose")
        rec = MessageRecord(message=msg, inbox_owner="manager-1", is_pending=False)
        result = render_chat_message(rec)
        assert "#4ecdc4" in result
        assert "🤖" in result
        assert "│" in result

    def test_worker_message_has_blue_border(self):
        msg = _make_message("delivery", sender="worker-1")
        rec = MessageRecord(message=msg, inbox_owner="worker-1", is_pending=False)
        result = render_chat_message(rec)
        assert "#45b7d1" in result
        assert "⚡" in result
        assert "│" in result

    def test_pending_message_shows_dot(self):
        msg = _make_message("ceo_feedback", sender="__ceo__")
        rec = MessageRecord(message=msg, inbox_owner="__ceo__", is_pending=True)
        result = render_chat_message(rec)
        assert "●" in result

    def test_time_is_displayed(self):
        msg = _make_message("ceo_feedback", sender="__ceo__")
        rec = MessageRecord(message=msg, inbox_owner="__ceo__", is_pending=False)
        result = render_chat_message(rec)
        assert ":" in result
