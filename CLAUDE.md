# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Test Commands

```bash
# Install in dev mode (includes pytest)
pip install -e ".[dev]"

# Run all tests
pytest

# Run a single test file
pytest tests/core/dispatch/test_decompose.py

# Run a single test function
pytest tests/core/dispatch/test_decompose.py::test_parse_manager_output -v

# Run tests matching a pattern
pytest -k "research" -v

# Run with coverage
pip install pytest-cov && pytest --cov=core --cov=agents --cov=cli --cov-report=term-missing

# Run the TUI (primary interaction mode)
studio

# Run CLI commands directly (skip TUI)
studio init --name test-project --description "Test"
studio task "Add search" --orchestrate --mock
studio status
studio project list
```

There is no lint/formatter configured yet. Python target is 3.11+.

## Architecture Overview

This is a **CEO-mode local multi-agent orchestration platform**. The user gives orders; the system manages a tree-structured "company" of external CLI coding agents (Claude Code, Hermes, OpenCode) working in isolated Git worktrees.

### Layer Stack

```
┌─ cli/studio.py ── CLI (argparse) + TUI (Textual) entry point
├─ cli/tui/app.py ── Textual App with screen stack (welcome → hub → onboarding → briefing → dashboard → review)
├─ core/dispatch/ ── Task lifecycle: create → decompose (manager) → assign (workers) → review → merge
├─ core/org/      ── Tree-structured org chart (OrgTree) with RBAC permission inheritance
├─ core/workspace/ ── Git worktree isolation (one per worker task)
├─ agents/         ── Subprocess adapter layer for external Agent CLIs
├─ core/platform/  ── Shared middleware: skills registry, MCP registry, file-backed memory store
├─ core/research/  ── Web search + Agent synthesis → project profile + org template selection
├─ core/rbac/      ── Skill/MCP/memory permission resolution along org tree
├─ supervisor/     ── Go gRPC daemon (optional; Python PortRegistry/ProcessRegistry fallback)
└─ config/         ── YAML: agents.yaml, models.yaml, platform.yaml, templates/
```

### Agent Adapter Reality

Despite `agents.yaml` listing 7 agents (claude-code, hermes, opencode, aider, goose, codex, gemini-cli), there is **only one adapter class**: `ClaudeCodeAdapter` in `agents/claude_code.py`. The `get_adapter()` function in `agents/registry.py` always returns `ClaudeCodeAdapter` regardless of which agent is configured. The adapter distinguishes agents only by `command` and `flags` from YAML config. All agents are invoked via `subprocess.run()`.

Key execution paths:
- **Headless (print mode)**: `agents/runner.py` → `build_command()` → `subprocess.run(cmd, capture_output=True)` — used for manager decomposition and research
- **Interactive (TUI mode)**: `core/terminal/agent_launcher.py` → `build_interactive_command()` → `spawn_agent_terminal()` — opens a new Windows Terminal tab
- **Windows shim resolution**: `agents/execute.py` `prepare_subprocess_argv()` handles `.cmd`/`.bat`/`.ps1` npm shims, resolving them to native `.exe` or `node` scripts

### Task Lifecycle (File-Driven State Machine)

```
pending → assigned → in_progress → submitted → in_review → approved/archived
                                                          → rejected → in_progress
                                                          → escalated (CEO decision)
            blocked (waits_on dependencies not met)
```

State is stored as YAML files in `tasks/active/{task_id}.yaml`. Inter-agent messages use JSON files in `agents/{id}/inbox/`. The `MessageBus` drains messages by renaming `.json` → `processed/`.

### Orchestration Flow

1. `studio task "..." --orchestrate` → `Dispatcher.create_task()` writes root task YAML + inbox message to manager
2. Manager agent (subprocess) decomposes task, outputs JSON after `---STUDIO_SUBTASKS_JSON---` marker
3. `parse_manager_output()` in `core/dispatch/decompose.py` extracts subtasks with assignee/waits_on
4. `apply_subtasks()` writes child task YAMLs, spawns worker terminals via `spawn_worker_agent_terminal()`
5. Workers write `.studio/DELIVER.json` when done; `poll_worker_deliveries()` detects and triggers manager review
6. Manager reviews (another subprocess), outputs verdict JSON after `---STUDIO_REVIEW_JSON---`

### Mock Mode

`--mock` flag skips real Agent calls. `generate_mock_subtasks()` in `decompose.py` creates default subtasks from `positions.yaml`. Essential for testing the orchestration pipeline without real Agent CLIs installed.

## Critical Safety Notes

**Shell injection risk on Windows**: When Agent commands use `.cmd`/`.bat` shims, `prepare_subprocess_argv()` falls back to `["cmd.exe", "/c", line]` where `line` is built with `subprocess.list2cmdline()`. Task descriptions containing `&`, `|`, or `%VAR%` could be interpreted by `cmd.exe`. Avoid passing untrusted user input through task descriptions without sanitization.

**`shell=True` in delivery.py**: `run_deliver_command()` uses `shell=True` to execute worker-provided `run_command`. While the command comes from the worker's own `DELIVER.json`, this is a risk surface.

**`shutil.rmtree` in project delete**: `delete_project()` with `remove_folder=True` recursively deletes the project directory. The only safeguard is checking the path is not the studio root.

**Worktree branch name collision**: `WorktreeManager.create()` uses `f"studio/{task_id}-{slug}"` with no retry or random suffix. Duplicate task_ids crash immediately.

## Key Design Decisions

- **No database**: All state in YAML/JSON files under `.studio/` and `projects/{id}/`
- **No web UI**: Pure CLI with Textual TUI; `studio` with no args launches the TUI
- **External agents only**: Platform never creates agents — it calls existing CLI tools via subprocess
- **Git worktree isolation**: Workers never see each other's in-progress code; only merged results are visible
- **Three-line defense for skills**: (1) Auto-load at spawn, (2) Manager mentions skills in task descriptions, (3) Reviewer checks compliance
- **BYOK policy**: Default `platform.yaml` sets `agents.policy: byok_only`, restricting to agents that work with third-party API keys
- **Go Supervisor is optional**: Python `PortRegistry` + `ProcessRegistry` in `core/supervisor/registry.py` provide full fallback

## Project Completion Status

This is **v0.1.0 — early prototype**. What works: project init, task creation, mock orchestration loop, org tree CRUD, TUI navigation, research/web-search pipeline. What's incomplete: real Agent-driven orchestration (depends on Agent output parsing reliability), expand/business-line features (hardcoded to mock research), memory store (file-backed, no vector search yet), MCP gateway (registry exists but gateway is empty config).

