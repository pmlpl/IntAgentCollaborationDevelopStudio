# cli/tui/screens/position_editor.py — 逐岗配置模态框
from __future__ import annotations

from copy import deepcopy
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Select, Static

from core.config.catalog import load_agents, load_models
from core.config.select_helpers import safe_select_value
from core.project import get_studio_root

# 汇报上级：Select 用内部 sentinel，避免 Select.NULL / "null" 键错误
_PARENT_TOP = "__top__"


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
        border: solid #58a6ff;
        background: #0f1729;
    }
    """

    def __init__(self, positions: list[dict[str, Any]]) -> None:
        super().__init__()
        self._positions = deepcopy(positions)
        self._overrides: dict[str, dict[str, Any]] = {}
        self._index = 0
        self._agent_options: list[tuple[str, str]] = []
        self._model_options: list[tuple[str, str]] = []

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
        self._agent_options = list(load_agents(root))
        self._model_options = list(load_models(root))
        self.query_one("#agent-select", Select).set_options(self._agent_options)
        self.query_one("#model-select", Select).set_options(self._model_options)
        self._load_position(0)

    def _ensure_agent_option(self, agent_id: str) -> None:
        """岗位已有 agent 不在列表时补一项（例如策略过滤后仍要显示当前值）。"""
        if not agent_id:
            return
        ids = {v for _, v in self._agent_options}
        if agent_id in ids:
            return
        label = f"{agent_id}（当前）"
        self._agent_options.append((label, agent_id))
        self.query_one("#agent-select", Select).set_options(self._agent_options)

    def _ensure_model_option(self, model_id: str) -> None:
        if not model_id:
            return
        ids = {v for _, v in self._model_options}
        if model_id in ids:
            return
        label = f"{model_id}（当前）"
        self._model_options.append((label, model_id))
        self.query_one("#model-select", Select).set_options(self._model_options)

    def _current(self) -> dict[str, Any]:
        return self._positions[self._index]

    def _save_current_to_overrides(self) -> None:
        pos = self._current()
        pid = pos["id"]
        agent_val = self.query_one("#agent-select", Select).value
        model_val = self.query_one("#model-select", Select).value
        self._overrides[pid] = {
            "name": self.query_one("#name-input", Input).value.strip(),
            "title": self.query_one("#title-input", Input).value.strip(),
            "agent": str(agent_val) if agent_val not in (None, Select.BLANK) else pos.get("agent"),
            "model": str(model_val) if model_val not in (None, Select.BLANK) else pos.get("model"),
        }
        self._overrides[pid]["parent"] = self._parent_value()

    def _parent_value(self) -> str | None:
        val = self.query_one("#parent-select", Select).value
        if val in (None, Select.BLANK, _PARENT_TOP):
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

        agent_id = str(merged.get("agent") or "")
        model_id = str(merged.get("model") or "")
        self._ensure_agent_option(agent_id)
        self._ensure_model_option(model_id)
        safe_select_value(self.query_one("#agent-select", Select), agent_id or None)
        safe_select_value(self.query_one("#model-select", Select), model_id or None)

        parent_opts: list[tuple[str, str]] = [("无（顶层主管）", _PARENT_TOP)]
        for p in self._positions:
            if p["id"] == pid:
                continue
            if p.get("is_manager") or p.get("parent") is None:
                parent_opts.append((f"{p.get('name')} ({p['id']})", p["id"]))
        parent_sel = self.query_one("#parent-select", Select)
        parent_sel.set_options(parent_opts)
        parent = merged.get("parent")
        safe_select_value(parent_sel, _PARENT_TOP if parent is None else str(parent))

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
