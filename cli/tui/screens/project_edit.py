# cli/tui/screens/project_edit.py — 编辑项目 registry 信息
from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static

from core.project import get_studio_root, update_project


class ProjectEditModal(ModalScreen[bool]):
    """编辑项目名称、定位、文件夹路径。"""

    DEFAULT_CSS = """
    ProjectEditModal {
        align: center middle;
    }
    #edit-box {
        width: 72;
        height: auto;
        padding: 1 2;
        border: round #89b4fa;
        background: #181825;
    }
    """

    def __init__(self, entry: dict) -> None:
        super().__init__()
        self.entry = entry

    def compose(self) -> ComposeResult:
        with Vertical(id="edit-box", classes="panel-box"):
            yield Static(f"[bold]编辑项目[/]  [dim](id: {self.entry.get('id')})[/]")
            yield Static("显示名称", classes="muted")
            yield Input(value=self.entry.get("name") or "", id="name-input")
            yield Static("项目定位 / 做什么", classes="muted")
            yield Input(value=self.entry.get("purpose") or "", id="purpose-input")
            yield Static("项目文件夹路径", classes="muted")
            yield Input(value=self.entry.get("path") or "", id="path-input")
            with Horizontal():
                yield Button("保存", variant="success", id="save")
                yield Button("取消", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(False)
            return
        if event.button.id == "save":
            self._save()

    def _save(self) -> None:
        root = get_studio_root()
        project_id = self.entry["id"]
        name = self.query_one("#name-input", Input).value.strip()
        purpose = self.query_one("#purpose-input", Input).value.strip()
        path = self.query_one("#path-input", Input).value.strip()
        if not path:
            return
        update_project(
            root,
            project_id,
            name=name or project_id,
            purpose=purpose or name or project_id,
            path=Path(path),
        )
        self.dismiss(True)
