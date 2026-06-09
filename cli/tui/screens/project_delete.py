# cli/tui/screens/project_delete.py — 删除项目二次确认
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class ProjectDeleteModal(ModalScreen[bool]):
    """删除项目确认；返回 True 表示用户确认删除整个项目文件夹。"""

    DEFAULT_CSS = """
    ProjectDeleteModal {
        align: center middle;
    }
    #delete-box {
        width: 68;
        height: auto;
        padding: 1 2;
        border: round #f38ba8;
        background: #181825;
    }
    """

    def __init__(self, entry: dict) -> None:
        super().__init__()
        self.entry = entry

    def compose(self) -> ComposeResult:
        title = self.entry.get("name") or self.entry.get("id")
        pid = self.entry.get("id") or ""
        path = self.entry.get("path") or ""
        with Vertical(id="delete-box", classes="panel-box"):
            yield Static("[bold red]确认删除项目？[/]")
            yield Static(
                f"项目: [bold]{title}[/]  [dim]({pid})[/]\n"
                f"文件夹:\n{path}\n\n"
                "[yellow]将永久删除整个项目文件夹[/]（含源码与 .studio/ 数据）。\n"
                "此操作不可恢复。",
            )
            with Horizontal():
                yield Button("确认删除", variant="error", id="confirm")
                yield Button("取消", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(False)
        elif event.button.id == "confirm":
            self.dismiss(True)
