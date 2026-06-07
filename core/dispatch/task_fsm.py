# core/dispatch/task_fsm.py — 任务生命周期状态机
VALID_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"assigned", "blocked"},
    "assigned": {"in_progress", "blocked"},
    "blocked": {"assigned"},
    "in_progress": {"submitted"},
    "submitted": {"in_review"},
    "in_review": {"approved", "rejected", "escalated"},
    "approved": {"archived"},
    "rejected": {"in_progress"},
    "escalated": {"archived"},
}


class InvalidTransition(Exception):
    """非法状态迁移。"""


class TaskFSM:
    """任务状态机。"""

    def __init__(self, initial: str = "pending"):
        if initial not in VALID_TRANSITIONS and initial != "archived":
            raise InvalidTransition(f"unknown state: {initial}")
        self.state = initial

    def transition(self, target: str) -> None:
        allowed = VALID_TRANSITIONS.get(self.state, set())
        if target not in allowed:
            raise InvalidTransition(f"cannot go from {self.state!r} to {target!r}")
        self.state = target

    def can_transition(self, target: str) -> bool:
        return target in VALID_TRANSITIONS.get(self.state, set())
