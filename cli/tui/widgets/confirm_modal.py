# cli/tui/widgets/confirm_modal.py — 通用确认对话框
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class ConfirmModal(ModalScreen[bool]):
    """双按钮确认框；返回 True 表示确认。"""

    DEFAULT_CSS = """
    ConfirmModal {
        align: center middle;
    }
    #confirm-box {
        width: 60;
        height: auto;
        padding: 1 2;
        border: round #89b4fa;
        background: #181825;
    }
    """

    def __init__(self, message: str, *, confirm_label: str = "确认", cancel_label: str = "取消") -> None:
        super().__init__()
        self.message = message
        self.confirm_label = confirm_label
        self.cancel_label = cancel_label

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box", classes="panel-box"):
            yield Static(self.message)
            with Horizontal():
                yield Button(self.confirm_label, variant="success", id="ok")
                yield Button(self.cancel_label, id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "ok")
