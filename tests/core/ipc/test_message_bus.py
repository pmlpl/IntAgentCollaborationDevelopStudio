from pathlib import Path

from core.ipc.message_bus import Message, MessageBus


def test_deliver_and_drain(tmp_path: Path):
    inbox = tmp_path / "inbox"
    bus = MessageBus(inbox)
    msg = Message(
        id="msg-001",
        type="task_assign",
        sender="laowang",
        recipient="dazhuang",
        task_id="task-001",
        payload={"description": "写 API"},
    )
    bus.deliver(msg)
    assert (inbox / "msg-001.json").exists()
    drained = bus.drain()
    assert len(drained) == 1
    assert drained[0].payload["description"] == "写 API"
    assert not (inbox / "msg-001.json").exists()
    assert (inbox / "processed" / "msg-001.json").exists()
