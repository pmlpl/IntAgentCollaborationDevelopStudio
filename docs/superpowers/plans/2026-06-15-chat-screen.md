# ChatScreen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a full-featured CEO ↔ Manager chat screen in the TUI, with RichLog message stream, slash commands, tab completion, and multi-agent message visibility.

**Architecture:** A new `ChatScreen` (Textual Screen) uses `RichLog` for append-only message rendering and a custom `ChatInput` widget with `/command` + `@mention` tab completion. Messages flow through the existing `MessageLogCollector` (poll) and `send_ceo_feedback()` (send). A new `classify_role()` function in `core/ipc/message_log.py` maps message types to visual roles (CEO/Manager/Worker/System).

**Tech Stack:** Python 3.11+, Textual (RichLog, Input, Screen), existing `core/ipc/message_bus.py` + `core/ipc/message_log.py` + `core/ipc/ceo_chat.py`

**Spec:** `docs/superpowers/specs/2026-06-15-chat-screen-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `core/ipc/message_log.py` | Modify | Add `classify_role()` and `ChatRole` enum for message→role mapping |
| `cli/tui/widgets/chat_input.py` | Create | `ChatInput` widget (Input + tab completion + slash commands + history) and `render_chat_message()` |
| `cli/tui/screens/chat.py` | Create | `ChatScreen` (RichLog + polling + keyboard bindings + send flow) |
| `cli/tui/theme.tcss` | Modify | Add `#ChatScreen`, `#chat-messages`, `#chat-input`, `#chat-header`, `#chat-status` rules |
| `cli/tui/app.py` | Modify | Register `"chat": ChatScreen` |
| `cli/tui/screens/dashboard.py` | Modify | Repurpose `c` key to push ChatScreen; remove inline chat input |
| `tests/tui/test_chat_message.py` | Create | Unit tests for `render_chat_message()` |
| `tests/tui/test_chat_input.py` | Create | Unit tests for `ChatInput` (slash parsing, completion, history) |
| `tests/tui/test_chat_screen.py` | Create | Integration tests for `ChatScreen` polling and send flow |

---

### Task 1: Add `ChatRole` enum and `classify_role()` to message_log.py

**Files:**
- Modify: `core/ipc/message_log.py`
- Test: `tests/tui/test_chat_message.py`

- [ ] **Step 1: Write the failing test**

Create `tests/tui/test_chat_message.py`:

```python
"""Tests for chat message rendering and role classification."""
from __future__ import annotations

from core.ipc.message_bus import Message
from core.ipc.message_log import MessageRecord, classify_role, ChatRole


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/tui/test_chat_message.py::TestClassifyRole -v`
Expected: FAIL — `cannot import name 'classify_role' from 'core.ipc.message_log'`

- [ ] **Step 3: Write minimal implementation**

Add to the top of `core/ipc/message_log.py` (after existing imports):

```python
from enum import Enum


class ChatRole(Enum):
    """聊天消息的角色分类。"""
    CEO = "ceo"
    MANAGER = "manager"
    WORKER = "worker"
    SYSTEM = "system"


# 消息类型 → 角色映射
_TYPE_ROLE_MAP: dict[str, ChatRole] = {
    "ceo_feedback": ChatRole.CEO,
    "ceo_review": ChatRole.CEO,
    "task_decompose": ChatRole.MANAGER,
    "reply": ChatRole.MANAGER,
    "delivery": ChatRole.WORKER,
    "review_request": ChatRole.WORKER,
    "escalation": ChatRole.WORKER,
}


def classify_role(msg: Message) -> ChatRole:
    """根据消息类型和发送者判断角色。"""
    if msg.type in _TYPE_ROLE_MAP:
        return _TYPE_ROLE_MAP[msg.type]
    # 回退：根据 sender 前缀猜测
    if msg.sender.startswith("worker") or msg.sender.startswith("wrk"):
        return ChatRole.WORKER
    if msg.sender.startswith("manager") or msg.sender.startswith("mgr"):
        return ChatRole.MANAGER
    return ChatRole.SYSTEM
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/tui/test_chat_message.py::TestClassifyRole -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add core/ipc/message_log.py tests/tui/test_chat_message.py
git commit -m "feat(chat): add ChatRole enum and classify_role() to message_log"
```

---

### Task 2: Add `render_chat_message()` to widgets

**Files:**
- Create: `cli/tui/widgets/chat_input.py` (first part — rendering only; input widget comes in Task 3)
- Test: `tests/tui/test_chat_message.py` (extend)

- [ ] **Step 1: Write the failing tests**

Add to `tests/tui/test_chat_message.py`:

```python
from cli.tui.widgets.chat_input import render_chat_message


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
        # 时间格式 HH:MM:SS
        assert ":" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/tui/test_chat_message.py::TestRenderChatMessage -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cli.tui.widgets.chat_input'`

- [ ] **Step 3: Create `cli/tui/widgets/chat_input.py` with `render_chat_message()`**

```python
"""聊天输入组件和消息渲染。"""
from __future__ import annotations

from datetime import datetime
from core.ipc.message_log import MessageRecord, ChatRole, classify_role


# 角色 → (图标, 显示名, Rich 颜色, 是否有左边框)
_ROLE_STYLE: dict[ChatRole, tuple[str, str, str, bool]] = {
    ChatRole.CEO:     ("👤", "CEO",    "#ff6b9d", False),
    ChatRole.MANAGER: ("🤖", "Manager", "#4ecdc4", True),
    ChatRole.WORKER:  ("⚡", "Worker",  "#45b7d1", True),
    ChatRole.SYSTEM:  ("🔔", "系统",    "#f9ca24", True),
}


def _format_time(iso_str: str) -> str:
    """ISO 时间字符串 → HH:MM:SS。"""
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%H:%M:%S")
    except (ValueError, TypeError):
        return "??:??:??"


def _extract_text(msg) -> str:
    """从 payload 中提取文本摘要。"""
    payload = msg.payload or {}
    text = payload.get("text", "")
    if not text:
        # 尝试从其他 payload 字段提取
        for key in ("summary", "result", "verdict"):
            if key in payload:
                val = payload[key]
                if isinstance(val, str):
                    text = val
                    break
                elif isinstance(val, dict):
                    text = val.get("text", str(val)[:120])
                    break
    # 截断
    if len(text) > 200:
        text = text[:197] + "..."
    return text


def render_chat_message(rec: MessageRecord) -> str:
    """将一条 MessageRecord 渲染为 Rich markup 字符串。

    返回的字符串可直接传入 RichLog.write()。
    """
    msg = rec.message
    role = classify_role(msg)
    icon, name, color, has_border = _ROLE_STYLE[role]
    t = _format_time(msg.created_at)
    pending = " [yellow]●[/]" if rec.is_pending else ""
    text = _extract_text(msg)

    # 构建头部行
    header = f"[{color}]{icon} {name}[/] [dim]{t}[/]{pending}"

    if has_border:
        border = f"[{color}]│[/]"
        lines = [f"{border} {header}"]
        if text:
            for line in text.split("\n"):
                lines.append(f"{border}   {line}")
    else:
        lines = [header]
        if text:
            for line in text.split("\n"):
                lines.append(f"   {line}")

    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/tui/test_chat_message.py -v`
Expected: 13 passed (8 classify_role + 5 render_chat_message)

- [ ] **Step 5: Commit**

```bash
git add cli/tui/widgets/chat_input.py tests/tui/test_chat_message.py
git commit -m "feat(chat): add render_chat_message() with role-based styling"
```

---

### Task 3: Build `ChatInput` widget with slash completion and history

**Files:**
- Modify: `cli/tui/widgets/chat_input.py`
- Test: `tests/tui/test_chat_input.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/tui/test_chat_input.py`:

```python
"""Tests for ChatInput widget: slash parsing, completion, history."""
from __future__ import annotations

import pytest

from cli.tui.widgets.chat_input import (
    ChatInput,
    SlashCommand,
    parse_slash_command,
    get_completions,
)


class TestParseSlashCommand:
    def test_slash_task(self):
        cmd = parse_slash_command("/task Add search feature")
        assert cmd is not None
        assert cmd.name == "task"
        assert cmd.args == "Add search feature"

    def test_slash_status_no_args(self):
        cmd = parse_slash_command("/status")
        assert cmd is not None
        assert cmd.name == "status"
        assert cmd.args == ""

    def test_slash_history_with_number(self):
        cmd = parse_slash_command("/history 50")
        assert cmd is not None
        assert cmd.name == "history"
        assert cmd.args == "50"

    def test_not_a_slash_command(self):
        cmd = parse_slash_command("hello world")
        assert cmd is None

    def test_slash_only(self):
        cmd = parse_slash_command("/")
        assert cmd is None


class TestGetCompletions:
    def test_slash_ta_completes_to_task(self):
        results = get_completions("/ta")
        assert "/task" in results

    def test_slash_st_completes_to_status(self):
        results = get_completions("/st")
        assert "/status" in results

    def test_at_man_completes(self):
        results = get_completions("@man", agent_ids=["manager-1", "worker-1"])
        assert "@manager-1" in results

    def test_empty_input_no_completions(self):
        results = get_completions("")
        assert results == []

    def test_unknown_slash_no_completions(self):
        results = get_completions("/zzz")
        assert results == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/tui/test_chat_input.py -v`
Expected: FAIL — `cannot import name 'SlashCommand' from 'cli.tui.widgets.chat_input'`

- [ ] **Step 3: Implement slash parsing and completion**

Add the following to `cli/tui/widgets/chat_input.py` (append after `render_chat_message`):

```python
from dataclasses import dataclass
from textual.widgets import Input
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static


# ── Slash 命令定义 ──

COMMANDS: dict[str, str] = {
    "task": "下派新任务给 Manager",
    "review": "查看/审批任务评审结果",
    "status": "显示当前编排进度概览",
    "escalations": "列出所有待 CEO 决策的升级",
    "history": "加载最近 n 条历史消息",
    "filter": "只显示指定 Agent 的消息",
    "clear": "清空当前屏幕（不删数据）",
    "help": "显示所有命令帮助",
}


@dataclass
class SlashCommand:
    """解析后的斜杠命令。"""
    name: str
    args: str


def parse_slash_command(text: str) -> SlashCommand | None:
    """解析用户输入为斜杠命令。如果不是 / 开头则返回 None。"""
    text = text.strip()
    if not text.startswith("/") or len(text) < 2:
        return None
    parts = text[1:].split(maxsplit=1)
    name = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""
    return SlashCommand(name=name, args=args)


def get_completions(
    text: str,
    agent_ids: list[str] | None = None,
) -> list[str]:
    """根据当前输入返回补全候选列表。"""
    text = text.strip()
    if not text:
        return []

    if agent_ids is None:
        agent_ids = []

    results: list[str] = []

    # / 命令补全
    if text.startswith("/"):
        prefix = text[1:].lower()
        for cmd_name in COMMANDS:
            if cmd_name.startswith(prefix) and cmd_name != prefix:
                results.append(f"/{cmd_name}")

    # @ 提及补全
    elif text.startswith("@"):
        prefix = text[1:].lower()
        for agent_id in agent_ids:
            if agent_id.lower().startswith(prefix) and agent_id.lower() != prefix:
                results.append(f"@{agent_id}")

    return results


# ── ChatInput Widget ──

class ChatInput(Input):
    """带补全功能的聊天输入框。"""

    def __init__(self, agent_ids: list[str] | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._agent_ids = agent_ids or []
        self._history: list[str] = []
        self._history_idx: int = -1
        self._completions: list[str] = []
        self._completion_idx: int = -1

    def push_history(self, text: str) -> None:
        """记录一条已发送的消息到历史。"""
        if text and (not self._history or self._history[-1] != text):
            self._history.append(text)
            if len(self._history) > 100:
                self._history = self._history[-100:]
        self._history_idx = -1

    def on_key(self, event) -> None:
        """拦截 Tab / Up / Down 键。"""
        if event.key == "tab":
            self._handle_tab()
            event.prevent_default()
        elif event.key == "up" and self.value == "":
            self._history_prev()
            event.prevent_default()
        elif event.key == "down" and self.value == "":
            self._history_next()
            event.prevent_default()

    def _handle_tab(self) -> None:
        """Tab 补全：循环补全候选。"""
        if not self.value:
            return

        if not self._completions or self._completion_idx == -1:
            # 第一次 Tab：生成候选列表
            self._completions = get_completions(self.value, self._agent_ids)
            if not self._completions:
                return
            self._completion_idx = 0
        else:
            # 后续 Tab：循环
            self._completion_idx = (self._completion_idx + 1) % len(self._completions)

        self.value = self._completions[self._completion_idx]

    def _history_prev(self) -> None:
        """上箭头：浏览历史（从新到旧）。"""
        if not self._history:
            return
        if self._history_idx == -1:
            self._history_idx = len(self._history) - 1
        elif self._history_idx > 0:
            self._history_idx -= 1
        self.value = self._history[self._history_idx]

    def _history_next(self) -> None:
        """下箭头：浏览历史（从旧到新）。"""
        if self._history_idx == -1:
            return
        if self._history_idx < len(self._history) - 1:
            self._history_idx += 1
            self.value = self._history[self._history_idx]
        else:
            self._history_idx = -1
            self.value = ""

    def _on_input_changed(self, event) -> None:
        """输入变化时重置补全状态。"""
        self._completions = []
        self._completion_idx = -1
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/tui/test_chat_input.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add cli/tui/widgets/chat_input.py tests/tui/test_chat_input.py
git commit -m "feat(chat): add ChatInput widget with slash completion and history"
```

---

### Task 4: Add TCSS styles for ChatScreen

**Files:**
- Modify: `cli/tui/theme.tcss`

- [ ] **Step 1: Append ChatScreen styles**

Append the following to the end of `cli/tui/theme.tcss`:

```css
/* ── ChatScreen ── */

#ChatScreen {
    layout: vertical;
}

#chat-header {
    height: 3;
    background: #161b22;
    border: solid #30363d;
    padding: 0 1;
    content-align: left middle;
    color: #8b949e;
}

#chat-messages {
    height: 1fr;
    border: solid #30363d;
    background: #0d1117;
    scrollbar-color: #30363d;
    scrollbar-color-hover: #484f58;
    padding: 0 1;
}

#chat-status {
    height: 1;
    background: #161b22;
    color: #8b949e;
    padding: 0 1;
}

#chat-input-area {
    height: auto;
    max-height: 5;
    border: solid #30363d;
    background: #161b22;
}

#chat-input {
    width: 1fr;
    max-height: 3;
    border: none;
    background: #161b22;
}

#chat-input:focus {
    border: none;
}

#chat-completion {
    height: auto;
    max-height: 8;
    background: #161b22;
    border: solid #30363d;
    display: none;
    overflow-y: auto;
}

#chat-completion.visible {
    display: block;
}

.completion-item {
    height: 1;
    padding: 0 1;
    color: #c9d1d9;
}

.completion-item.highlighted {
    background: #1f6feb;
    color: #ffffff;
}
```

- [ ] **Step 2: Verify no TCSS syntax errors**

Run: `python -c "from textual.css.parse import parse; parse(open('cli/tui/theme.tcss').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add cli/tui/theme.tcss
git commit -m "feat(chat): add TCSS styles for ChatScreen widgets"
```

---

### Task 5: Build `ChatScreen` — compose, mount, poll, send

**Files:**
- Create: `cli/tui/screens/chat.py`
- Test: `tests/tui/test_chat_screen.py`

- [ ] **Step 1: Write the failing test**

Create `tests/tui/test_chat_screen.py`:

```python
"""Tests for ChatScreen polling and send flow."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.ipc.message_bus import Message
from core.ipc.message_log import MessageRecord


class TestChatScreenImports:
    """Smoke test: ChatScreen can be imported and instantiated."""

    def test_import(self):
        from cli.tui.screens.chat import ChatScreen
        assert ChatScreen is not None

    def test_has_bindings(self):
        from cli.tui.screens.chat import ChatScreen
        binding_keys = [b[0] for b in ChatScreen.BINDINGS]
        assert "escape" in binding_keys
        assert "ctrl+home" in binding_keys
        assert "ctrl+end" in binding_keys
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/tui/test_chat_screen.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cli.tui.screens.chat'`

- [ ] **Step 3: Create `cli/tui/screens/chat.py`**

```python
"""主管聊天频道 — CEO ↔ Manager 全场景对话界面。"""
from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, RichLog, Static

from cli.tui.widgets.chat_input import (
    ChatInput,
    SlashCommand,
    render_chat_message,
    parse_slash_command,
    COMMANDS,
)
from core.dispatch.dispatcher import get_dispatcher
from core.ipc.ceo_chat import send_ceo_feedback
from core.ipc.message_log import MessageLogCollector, classify_role, ChatRole


class ChatScreen(Screen):
    """主管聊天频道。"""
    BINDINGS = [
        ("escape", "back", "返回"),
        ("ctrl+home", "scroll_top", "顶部"),
        ("ctrl+end", "scroll_bottom", "底部"),
        ("s", "show_status", "状态"),
        ("e", "show_escalations", "升级"),
    ]

    def __init__(
        self,
        project_dir: str | Path | None = None,
        manager_id: str = "",
        task_id: str | None = None,
    ) -> None:
        super().__init__()
        self._project_dir = Path(project_dir) if project_dir else None
        self._manager_id = manager_id
        self._task_id = task_id or ""
        self._collector: MessageLogCollector | None = None
        self._auto_scroll: bool = True
        self._last_task_state: str | None = None

    # ── 布局 ──

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(self._build_header_text(), id="chat-header")
        yield RichLog(id="chat-messages", wrap=True, highlight=True)
        yield Static("", id="chat-status")
        yield ChatInput(
            agent_ids=self._agent_ids(),
            placeholder="输入指令… Tab:补全 /:命令",
            id="chat-input",
        )
        yield Footer()

    def _build_header_text(self) -> str:
        parts = ["📡 主管频道"]
        if self._manager_id:
            parts.append(f"Manager: {self._manager_id}")
        if self._task_id:
            parts.append(f"任务: {self._task_id}")
        parts.append("esc:返回")
        return " │ ".join(parts)

    def _agent_ids(self) -> list[str]:
        """获取当前项目中的 Agent ID 列表（用于 @ 补全）。"""
        if not self._project_dir:
            return []
        agents_dir = self._project_dir / "agents"
        if not agents_dir.exists():
            return []
        return sorted(d.name for d in agents_dir.iterdir() if d.is_dir())

    # ── 生命周期 ──

    def on_mount(self) -> None:
        """初始化 collector + 加载历史 + 启动轮询。"""
        self._sync_context()
        if self._project_dir:
            self._collector = MessageLogCollector(self._project_dir)
            self._load_history()
        self.set_interval(2.0, self._poll_messages)

    def _sync_context(self) -> None:
        """从 StudioApp 获取项目上下文。"""
        if self._project_dir:
            return
        try:
            app = self.app
            project_name = getattr(app, "project_name", None)
            if project_name:
                from core.project import get_studio_root
                root = get_studio_root()
                disp = get_dispatcher(root, project_name)
                self._project_dir = disp.project_dir
                self._manager_id = disp._root_manager_id()
        except Exception:
            pass

    def _load_history(self) -> None:
        """加载最近 30 条消息到 RichLog。"""
        if not self._collector:
            return
        records = self._collector.collect_new(limit_per_agent=15)
        if not records:
            return
        # 取最后 30 条
        recent = records[-30:]
        rich_log = self.query_one("#chat-messages", RichLog)
        rich_log.write(
            "[dim]── 会话开始 ──[/]\n",
            scroll_end=False,
        )
        for rec in recent:
            rich_log.write(
                render_chat_message(rec) + "\n",
                scroll_end=False,
            )

    # ── 轮询 ──

    def _poll_messages(self) -> None:
        """每 2 秒轮询新消息。"""
        if not self._collector:
            return

        new_records = self._collector.collect_new()
        if new_records:
            rich_log = self.query_one("#chat-messages", RichLog)
            for rec in new_records:
                rich_log.write(render_chat_message(rec) + "\n", scroll_end=self._auto_scroll)

        self._check_task_state()

    def _check_task_state(self) -> None:
        """检查任务状态变化，生成系统消息。"""
        if not self._project_dir:
            return
        try:
            app = self.app
            project_name = getattr(app, "project_name", None)
            if not project_name:
                return
            from core.project import get_studio_root
            root = get_studio_root()
            disp = get_dispatcher(root, project_name)
            if self._task_id:
                task = disp.load_task(self._task_id)
                state = task.get("state", "") if task else ""
                if state and state != self._last_task_state:
                    self._last_task_state = state
                    rich_log = self.query_one("#chat-messages", RichLog)
                    rich_log.write(
                        f"[#f9ca24]│[/] [#f9ca24]🔔 系统[/]\n"
                        f"[#f9ca24]│[/]    任务 {self._task_id} 状态变更: {state}\n",
                        scroll_end=self._auto_scroll,
                    )
        except Exception:
            pass

    # ── 发送消息 ──

    def on_input_submitted(self, event: Static) -> None:
        """处理输入提交。"""
        if event.input.id != "chat-input":
            return
        text = event.value.strip()
        if not text:
            return

        input_widget = self.query_one("#chat-input", ChatInput)
        input_widget.push_history(text)

        # 斜杠命令
        cmd = parse_slash_command(text)
        if cmd:
            self._handle_slash_command(cmd)
        else:
            self._send_to_manager(text)

        input_widget.value = ""

    def _send_to_manager(self, text: str) -> None:
        """发送自然语言消息给 Manager。"""
        if not self._project_dir or not self._manager_id:
            self.notify("未连接到项目或 Manager", severity="warning")
            return

        send_ceo_feedback(
            project_dir=self._project_dir,
            manager_id=self._manager_id,
            text=text,
            task_id=self._task_id,
        )

        # 立即在消息流中显示 CEO 消息
        rich_log = self.query_one("#chat-messages", RichLog)
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).strftime("%H:%M:%S")
        rich_log.write(
            f"[#ff6b9d]👤 CEO[/] [dim]{now}[/]\n"
            f"   {text}\n",
            scroll_end=self._auto_scroll,
        )
        self.notify("已发送给主管", severity="information")

    def _handle_slash_command(self, cmd: SlashCommand) -> None:
        """处理斜杠命令。"""
        handler = getattr(self, f"_cmd_{cmd.name}", None)
        if handler:
            handler(cmd.args)
        else:
            self.notify(f"未知命令: /{cmd.name}", severity="warning")

    def _cmd_status(self, args: str) -> None:
        """显示编排进度。"""
        self._show_system_message("正在获取状态…")
        # 触发状态刷新（通过 Dashboard 模式）
        self.notify("状态已刷新", severity="information")

    def _cmd_escalations(self, args: str) -> None:
        """显示待决策升级。"""
        self._show_system_message("查看待决策升级…")

    def _cmd_clear(self, args: str) -> None:
        """清空消息流。"""
        rich_log = self.query_one("#chat-messages", RichLog)
        rich_log.clear()
        rich_log.write("[dim]── 屏幕已清空 ──[/]\n")

    def _cmd_help(self, args: str) -> None:
        """显示命令帮助。"""
        lines = ["[#f9ca24]│[/] [#f9ca24]🔔 命令帮助[/]"]
        for name, desc in COMMANDS.items():
            lines.append(f"[#f9ca24]│[/]   [bold]/{name}[/] — {desc}")
        rich_log = self.query_one("#chat-messages", RichLog)
        rich_log.write("\n".join(lines) + "\n", scroll_end=self._auto_scroll)

    def _cmd_history(self, args: str) -> None:
        """加载更多历史消息。"""
        try:
            n = int(args) if args else 30
        except ValueError:
            n = 30
        if not self._collector:
            return
        self._collector.reset()
        records = self._collector.collect_new(limit_per_agent=n)
        recent = records[-n:]
        rich_log = self.query_one("#chat-messages", RichLog)
        for rec in recent:
            rich_log.write(render_chat_message(rec) + "\n", scroll_end=False)
        self.notify(f"已加载 {len(recent)} 条历史消息", severity="information")

    def _cmd_filter(self, args: str) -> None:
        """按 Agent 过滤消息（简单实现：提示暂不支持）。"""
        self.notify(f"过滤功能开发中: {args}", severity="information")

    def _cmd_task(self, args: str) -> None:
        """下派新任务。"""
        if not args:
            self.notify("用法: /task <任务描述>", severity="warning")
            return
        self._send_to_manager(f"[新任务] {args}")

    def _cmd_review(self, args: str) -> None:
        """查看审批。"""
        self.notify(f"查看审批: {args}", severity="information")

    def _show_system_message(self, text: str) -> None:
        """在消息流中显示系统消息。"""
        rich_log = self.query_one("#chat-messages", RichLog)
        rich_log.write(
            f"[#f9ca24]│[/] [#f9ca24]🔔 系统[/]\n"
            f"[#f9ca24]│[/]    {text}\n",
            scroll_end=self._auto_scroll,
        )

    # ── 快捷键 ──

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_scroll_top(self) -> None:
        self._auto_scroll = False
        rich_log = self.query_one("#chat-messages", RichLog)
        rich_log.scroll_home(animate=False)

    def action_scroll_bottom(self) -> None:
        self._auto_scroll = True
        rich_log = self.query_one("#chat-messages", RichLog)
        rich_log.scroll_end(animate=False)

    def action_show_status(self) -> None:
        self._cmd_status("")

    def action_show_escalations(self) -> None:
        self._cmd_escalations("")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/tui/test_chat_screen.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add cli/tui/screens/chat.py tests/tui/test_chat_screen.py
git commit -m "feat(chat): add ChatScreen with RichLog polling, send flow, slash commands"
```

---

### Task 6: Register ChatScreen in app.py and wire up dashboard

**Files:**
- Modify: `cli/tui/app.py`
- Modify: `cli/tui/screens/dashboard.py`

- [ ] **Step 1: Register in app.py**

In `cli/tui/app.py`, add import and SCREENS entry:

```python
# Add to imports (after existing screen imports):
from cli.tui.screens.chat import ChatScreen

# Add to SCREENS dict:
    "chat": ChatScreen,
```

- [ ] **Step 2: Repurpose `c` key in dashboard.py**

In `cli/tui/screens/dashboard.py`, change the BINDING and handler:

Change line 44:
```python
        ("c", "open_chat", "通信"),
```

Replace `action_focus_chat()` (lines 275-281) with:

```python
    def action_open_chat(self) -> None:
        if not self._ensure_project():
            self.notify("请先选择或创建项目", severity="warning")
            return
        disp = get_dispatcher(get_studio_root(), self.project_name)
        try:
            manager_id = disp._root_manager_id()
        except RuntimeError:
            self.notify("未找到主管", severity="warning")
            return
        self.app.push_screen(
            "chat",
        )
```

Note: ChatScreen's `on_mount` calls `_sync_context()` which auto-resolves project_dir and manager_id from `StudioApp`, so no constructor args are needed for the push_screen call.

- [ ] **Step 3: Verify existing tests still pass**

Run: `pytest tests/ -v --timeout=30 -x`
Expected: All existing tests pass

- [ ] **Step 4: Commit**

```bash
git add cli/tui/app.py cli/tui/screens/dashboard.py
git commit -m "feat(chat): register ChatScreen and wire c key from dashboard"
```

---

### Task 7: Run full test suite and manual smoke test

**Files:** None (verification only)

- [ ] **Step 1: Run all tests**

Run: `pytest tests/ -v --timeout=30`
Expected: All tests pass (existing + new chat tests)

- [ ] **Step 2: Manual smoke test — launch TUI**

Run: `studio`

Verify:
1. Dashboard loads normally
2. Press `c` → ChatScreen opens
3. Type a message → Enter → message appears in RichLog
4. Type `/help` → Enter → help text appears
5. Type `/clear` → Enter → screen clears
6. Press `Escape` → returns to Dashboard
7. Press `s` → status message appears

- [ ] **Step 3: Commit any fixes**

If any issues found during smoke test, fix and commit.

---

## Summary

| Task | What | New Files | Modified Files |
|------|------|-----------|----------------|
| 1 | ChatRole + classify_role() | — | `core/ipc/message_log.py` |
| 2 | render_chat_message() | `cli/tui/widgets/chat_input.py` | — |
| 3 | ChatInput widget | — | `cli/tui/widgets/chat_input.py` |
| 4 | TCSS styles | — | `cli/tui/theme.tcss` |
| 5 | ChatScreen | `cli/tui/screens/chat.py` | — |
| 6 | App registration + dashboard wiring | — | `cli/tui/app.py`, `cli/tui/screens/dashboard.py` |
| 7 | Full test + smoke test | — | (verification only) |

Total: 3 new files created, 5 files modified, 3 test files created. Each task is independently testable and committable.
