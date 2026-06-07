import pytest

from core.dispatch.task_fsm import InvalidTransition, TaskFSM


def test_pending_to_assigned():
    fsm = TaskFSM("pending")
    fsm.transition("assigned")
    assert fsm.state == "assigned"


def test_blocked_auto_unblock():
    fsm = TaskFSM("blocked")
    fsm.transition("assigned")
    assert fsm.state == "assigned"


def test_invalid_transition_raises():
    fsm = TaskFSM("pending")
    with pytest.raises(InvalidTransition):
        fsm.transition("approved")
