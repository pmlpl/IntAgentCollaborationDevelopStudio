# ChatScreen Design Spec

> CEO ↔ Supervisor Agent Chat Page for IntAgentCollaborationDevelopStudio TUI

**Date:** 2026-06-15
**Status:** Draft
**Author:** Claude Code (brainstorming session)

---

## 1. Overview

A new TUI screen (`ChatScreen`) that provides a full-featured chat interface for the CEO to communicate with the Manager/Supervisor Agent. Inspired by the terminal chat experiences of Claude Code and Codex CLI, built on Textual's `RichLog` widget with a Rich markup rendering pipeline.

### Goals

- **Bidirectional conversation**: CEO sends natural language commands; Manager replies with decomposition plans, questions, and status updates
- **Multi-agent visibility**: Messages from Manager, Workers, and system events appear in one unified stream
- **Slash command interface**: `/task`, `/review`, `/status`, `/escalations`, `/history`, `/filter`, `/clear`, `/help`
- **Tab completion**: Agent names (`@manager`), slash commands, task IDs
- **Consistent with existing TUI**: Uses the same `Header/Footer/Rich markup/Static` patterns as other screens

### Non-Goals

- No persistent message database — reuses existing file-based MessageBus
- No Markdown rendering — uses Rich markup for consistency with other screens
- No inline diff/code-block rendering — deferred to future iterations
- No real-time streaming from Agent LLM — messages appear when the Agent writes to inbox

---

## 2. Architecture

### Component Tree

```
ChatScreen (Screen)
├── Header(show_clock=True)
├── Static(#chat-header)          ── Channel title + task ID + keybind hints
├── RichLog(#chat-messages)       ── Core message stream (append-only)
├── Static(#chat-status)          ── Agent status line (optional, compact mode)
├── ChatInput(#chat-input)        ── Input widget with /command completion
└── Footer()
```

### Key Decision: RichLog over Static

Existing screens use `Static.update(rich_markup_string)` with full rebuilds on each poll cycle. This is acceptable for panels that change infrequently, but a chat message stream requires:
- **Append-only writes** (no rebuilding the entire history)
- **Auto-scroll to bottom** on new messages
- **Manual scroll-up** without losing position

Textual's `RichLog` widget provides all three natively. This is the first screen in the project to use `RichLog`.

### Data Flow

```
User Input ──→ ChatScreen
                 │
                 ├─ Plain text ──→ send_ceo_feedback() ──→ Manager inbox
                 ├─ /task cmd ──→ Dispatcher.create_task() ──→ New orchestration
                 ├─ /review ────→ Dispatcher.submit_review() ──→ Approve/reject
                 └─ /escalation → handle_ceo_decision() ──→ Escalation resolution

Poll (set_interval 2s)
                 │
                 └─ MessageLogCollector.collect_new()
                      │
                      ├─ New messages → RichLog.write() append + render
                      └─ Status changes → update #chat-status
```

### IPC Integration

The chat screen reuses the existing file-based MessageBus infrastructure:

| Layer | Component | Purpose |
|-------|-----------|---------|
| Send | `core/ipc/ceo_chat.py::send_ceo_feedback()` | Deliver CEO messages to Manager inbox |
| Receive | `core/ipc/message_log.py::MessageLogCollector` | Poll all agent inboxes, deduplicate |
| Render | `cli/tui/widgets/chat_input.py::render_chat_message()` | Format a single MessageRecord as Rich markup |

No new IPC mechanisms are needed. The `MessageLogCollector.collect_new()` method already handles deduplication via `_seen_ids` and returns only messages not yet seen.

---

## 3. Message Types and Rendering

### Color System

| Role | Icon | Color | Left Border | MessageBus types |
|------|------|-------|-------------|-----------------|
| CEO | `👤` | `#ff6b9d` (pink) | None | `ceo_feedback`, `ceo_review` |
| Manager | `🤖` | `#4ecdc4` (teal) | `│` 2px teal | `task_decompose`, `reply` |
| Worker | `⚡` | `#45b7d1` (blue) | `│` 2px blue | `delivery`, `review_request`, `escalation` |
| System | `🔔` | `#f9ca24` (yellow) | `│` 2px yellow | Auto-generated status events |
| Tool | `🔧` | `#a55eea` (purple) | `│` 2px purple | Tool call records (collapsible) |

### Message Format

```
{icon} {role_name}  {HH:MM:SS}
  {message body, indented 2ch}

  {optional: tool call detail, indented}
  {optional: metadata line in dim}
```

Agent messages (Manager, Worker, System, Tool) have a left border drawn via Rich markup: `[dim]│[/dim]` or colored border characters.

### Tool Call Messages

When an Agent invokes a tool (decompose, research, etc.), a purple-bordered collapsible entry appears:

```
│ 🔧 decompose — "搜索功能" → 2 子任务
```

Expand shows full input/output. Collapse is the default. Implemented via RichLog's ability to rewrite a line range (replace collapsed line with expanded block).

### System Event Messages

System messages are auto-generated, not from any agent inbox. Sources:
- Task state transitions (pending → assigned → in_progress → submitted → in_review)
- Worker errors or timeouts
- Escalation notifications
- Orchestration progress milestones

These are generated by polling `Dispatcher` state and comparing with previous snapshot.

---

## 4. Input System

### ChatInput Widget

A custom widget wrapping Textual's `Input` with additional behaviors:

```
▎ {user typing here...}        Enter:发送 │ Tab:补全 │ /:命令
```

**Prefix:** A styled `▎` character (cyan) as a visual prompt.

### Slash Command Completion

When the user types `/`, a dropdown appears with available commands:

| Command | Action | Example |
|---------|--------|---------|
| `/task <desc>` | Create new task via Dispatcher | `/task Add search feature` |
| `/review <id>` | View/approve review result | `/review T-001` |
| `/status` | Show orchestration progress overview | `/status` |
| `/escalations` | List pending CEO decisions | `/escalations` |
| `/history <n>` | Load n recent messages from processed/ | `/history 50` |
| `/filter <agent>` | Show only messages from agent | `/filter manager` |
| `/clear` | Clear screen (does not delete data) | `/clear` |
| `/help` | Show all commands | `/help` |

Implementation: The `ChatInput` widget intercepts keystrokes. When input starts with `/` and Tab is pressed, it completes from a hardcoded command list. The dropdown is rendered as a temporary `Static` overlay above the input.

### @-mention Completion

When the user types `@`, autocomplete from the list of known agent IDs:
- `@manager` — target the current Manager agent
- `@worker-1`, `@worker-2`, etc. — target specific Workers

The `@` prefix is informational only — all CEO messages go through `send_ceo_feedback()` to the Manager. The `@` mention is included in the message text for the Manager to interpret.

### Input History

Up/Down arrow keys cycle through previously sent messages (stored in an in-memory list, capped at 100). Only active when the Input is empty.

---

## 5. Polling and Lifecycle

### On Mount

1. Load the current project context from `StudioApp` (project_dir, manager_id, pending_task_id)
2. Initialize `MessageLogCollector` for the project
3. Load last 30 messages from `MessageLogCollector.scan_all()` into RichLog
4. Start `set_interval(2.0, self._poll_messages)`

### Poll Cycle (every 2s)

1. Call `collector.collect_new()` — returns only messages not in `_seen_ids`
2. For each new message, call `render_chat_message(msg)` → `rich_log.write(markup)`
3. Check `Dispatcher` state for task status changes → generate system messages if changed
4. If auto-scroll enabled, call `rich_log.scroll_end(animate=False)`
5. Update `#chat-status` with current Agent activity

### Auto-scroll Behavior

- Auto-scroll is **enabled by default** — new messages scroll to bottom
- When user manually scrolls up (via mouse wheel, Page Up, or arrow keys), auto-scroll is **paused**
- Pressing `Ctrl+End` or scrolling to the very bottom **re-enables** auto-scroll
- A `▼ 最新消息` indicator appears at the bottom when auto-scroll is active

### On Unmount

1. Stop the interval timer
2. No cleanup needed for `MessageLogCollector` (stateless, re-created on next mount)

---

## 6. Keyboard Bindings

| Key | Action | Scope |
|-----|--------|-------|
| `Escape` | Return to Dashboard | Screen |
| `Enter` | Send current input | ChatInput |
| `Tab` | Trigger /command or @completion | ChatInput |
| `Up` / `Down` | Input history (when input empty) | ChatInput |
| `Ctrl+Home` | Scroll to top of message stream | RichLog |
| `Ctrl+End` | Scroll to bottom + re-enable auto-scroll | RichLog |
| `s` | Shortcut for `/status` | Screen |
| `e` | Shortcut for `/escalations` | Screen |

---

## 7. Screen Navigation

### Entry Points

1. **From Dashboard:** Existing keybinding `c` (currently `action_focus_chat` which focuses the inline `#ceo-chat-input`) — repurposed to `app.push_screen("chat", ...)` instead. The inline CEO chat input on Dashboard is removed since ChatScreen supersedes it.
2. **From Dashboard orchestration mode:** Chat input `Enter` when in orchestration → opens ChatScreen with context

### Registration

Add to `StudioApp.SCREENS`:
```python
"chat": ChatScreen
```

### Context Passing

ChatScreen receives context via constructor:
```python
ChatScreen(project_dir: str, manager_id: str, task_id: str | None = None)
```

---

## 8. File Changes

### New Files

| File | Purpose |
|------|---------|
| `cli/tui/screens/chat.py` | ChatScreen class (Screen subclass) |
| `cli/tui/widgets/chat_input.py` | ChatInput widget + `render_chat_message()` function |
| `tests/tui/test_chat.py` | ChatScreen unit tests |

### Modified Files

| File | Change |
|------|--------|
| `cli/tui/app.py` | Register `"chat": ChatScreen` in SCREENS dict |
| `cli/tui/screens/dashboard.py` | Add keybinding to push ChatScreen; pass context |
| `cli/tui/theme.tcss` | Add `#ChatScreen` style rules (RichLog, ChatInput, header) |
| `core/ipc/ceo_chat.py` | Add `send_ceo_direct()` for non-orchestration chat |
| `core/ipc/message_log.py` | Add `classify_role()` method for message→role mapping |

---

## 9. Testing Strategy

### Unit Tests (`tests/tui/test_chat.py`)

1. **Message rendering**: Verify `render_chat_message()` produces correct Rich markup for each role type
2. **Slash command parsing**: Verify `/task`, `/review`, `/status` etc. are correctly parsed and dispatched
3. **Tab completion**: Verify `/ta` + Tab → `/task`, `@man` + Tab → `@manager`
4. **Auto-scroll logic**: Verify scroll pauses on manual scroll-up, resumes on Ctrl+End
5. **Polling integration**: Mock `MessageLogCollector.collect_new()` and verify messages appear in RichLog
6. **System event generation**: Verify Dispatcher state changes produce system messages

### Integration Tests

7. **End-to-end message flow**: Send `/task test` → verify task YAML created → verify message appears in chat
8. **Escalation flow**: Mock escalation message → verify `/escalations` shows it → submit decision

---

## 10. Design Decisions Log

| Decision | Alternatives Considered | Rationale |
|----------|------------------------|-----------|
| RichLog over Static | Static (current pattern) | Append-only writes + auto-scroll are essential for chat; Static requires full rebuild |
| 2s poll interval | 1.5s (Dashboard), 5s | Balance between responsiveness and CPU. Chat doesn't need sub-second updates |
| Slash commands in Input layer | Separate command palette widget | Simpler UX — no context switch. Claude Code uses same pattern |
| Left border for agents | Bubble style, indentation only | Matches terminal-native feel of Claude Code/Codex CLI; easier to implement in Rich markup |
| No persistent chat history file | SQLite, JSON log file | MessageBus already persists as JSON files in inbox/processed/. No need for redundant storage |
| Custom ChatInput over raw Input | Input + Dropdown widget | Need keystroke interception for Tab/Up/Down; raw Input doesn't support completion |
