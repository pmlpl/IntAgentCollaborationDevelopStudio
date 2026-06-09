# cli/tui/screens/position_editor.py — 逐岗配置模态框
from __future__ import annotations

from copy import deepcopy
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Select, Static

from core.config.catalog import load_agents, load_models
from core.project import get_studio_root


class PositionEditorModal(ModalScreen[dict[str, dict[str, Any]] | None]):
    """编辑各岗位的名称、Agent、模型、上级。"""

    DEFAULT_CSS = """
    PositionEditorModal {
        align: center middle;
    }
    #pos-edit-box {
        width: 72;
        height: auto;
        max-height: 90%;
        padding: 1 2;
        border: round #89b4fa;
        background: #181825;
    }
    """

    def __init__(self, positions: list[dict[str, Any]]) -> None:
        super().__init__()
        self._positions = deepcopy(positions)
        self._overrides: dict[str, dict[str, Any]] = {}
        self._index = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="pos-edit-box", classes="panel-box"):
            yield Static("[bold]逐岗配置[/]  ← → 切换岗位", id="pos-title")
            yield Static("", id="pos-meta", classes="muted")
            yield Static("花名", classes="muted")
            yield Input(id="name-input")
            yield Static("岗位头衔", classes="muted")
            yield Input(id="title-input")
            yield Static("Agent", classes="muted")
            yield Select([], id="agent-select")
            yield Static("模型", classes="muted")
            yield Select([], id="model-select")
            yield Static("汇报上级", classes="muted")
            yield Select([], id="parent-select")
            with Horizontal():
                yield Button("← 上一岗", id="prev")
                yield Button("下一岗 →", id="next")
            with Horizontal():
                yield Button("保存并关闭", variant="success", id="save")
                yield Button("取消", id="cancel")

    def on_mount(self) -> None:
        root = get_studio_root()
        agents = load_agents(root)
        models = load_models(root)
        self.query_one("#agent-select", Select).set_options(agents)
        self.query_one("#model-select", Select).set_options(models)
        self._load_position(0)

    def _current(self) -> dict[str, Any]:
        return self._positions[self._index]

    def _save_current_to_overrides(self) -> None:
        pos = self._current()
        pid = pos["id"]
        self._overrides[pid] = {
            "name": self.query_one("#name-input", Input).value.strip(),
            "title": self.query_one("#title-input", Input).value.strip(),
            "agent": str(self.query_one("#agent-select", Select).value or pos.get("agent")),
            "model": str(self.query_one("#model-select", Select).value or pos.get("model")),
        }
        parent = self._parent_value()
        self._overrides[pid]["parent"] = parent

    def _parent_value(self) -> str | None:
        val = self.query_one("#parent-select", Select).value
        if val is Select.BLANK or val is None or val == "null":
            return None
        return str(val)

    def _load_position(self, index: int) -> None:
        self._index = max(0, min(index, len(self._positions) - 1))
        pos = self._current()
        pid = pos["id"]
        merged = {**pos, **self._overrides.get(pid, {})}

        self.query_one("#pos-title", Static).update(
            f"[bold]逐岗配置[/]  {self._index + 1}/{len(self._positions)} · {merged.get('title')}"
        )
        self.query_one("#pos-meta", Static).update(f"岗位 id: {pid}（内部标识，不可改）")
        self.query_one("#name-input", Input).value = str(merged.get("name") or "")
        self.query_one("#title-input", Input).value = str(merged.get("title") or "")

        agent_sel = self.query_one("#agent-select", Select)
        model_sel = self.query_one("#model-select", Select)
        agent_sel.value = merged.get("agent") or Select.BLANK
        model_sel.value = merged.get("model") or Select.BLANK

        parent_opts: list[tuple[str, str | None]] = [("无（顶层主管）", "null")]
        for p in self._positions:
            if p["id"] == pid:
                continue
            if p.get("is_manager") or p.get("parent") is None:
                parent_opts.append((f"{p.get('name')} ({p['id']})", p["id"]))
        parent_sel = self.query_one("#parent-select", Select)
        parent_sel.set_options(parent_opts)
        parent = merged.get("parent")
        parent_sel.value = "null" if parent is None else str(parent)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "save":
            self._save_current_to_overrides()
            self.dismiss(self._overrides)
        elif event.button.id == "prev":
            self._save_current_to_overrides()
            self._load_position(self._index - 1)
        elif event.button.id == "next":
            self._save_current_to_overrides()
            self._load_position(self._index + 1)
