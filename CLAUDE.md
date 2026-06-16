# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Test Commands

```bash
# Install in dev mode (includes pytest)
pip install -e ".[dev]"

# Run all tests (164 tests, 36 test modules)
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
studio agent status                   # Agent health overview
studio agent check --no-smoke         # Quick agent availability check
studio expand business "description"  # Expand org with new business line
studio status
studio project list
```

No lint/formatter configured. Python target is 3.11+.

## Architecture Overview

This is a **CEO-mode local multi-agent orchestration platform**. The user gives orders; the system manages a tree-structured "company" of external CLI coding agents working in isolated Git worktrees.

### Layer Stack

```
┌─ cli/studio.py ──── CLI (argparse) + TUI (Textual) entry point
├─ cli/tui/ ───────── 11 screens + 5 widgets (welcome→hub→onboarding→dashboard→review→expand…)
├─ cli/agent_worker.py ── Agent worker modes: decompose / work / review / watch (PID-persistent)
├─ core/dispatch/ ──── Task lifecycle + 6-stage orchestration progress tracker
├─ core/org/ ───────── Tree-structured org chart (OrgTree) with RBAC permission inheritance
├─ core/workspace/ ─── Git worktree isolation (one per worker task)
├─ core/config/ ────── Agent policy, catalog, enable/disable toggle (30s cache)
├─ core/terminal/ ──── Agent launcher, install launcher, subprocess spawner
├─ agents/ ─────────── Adapter classes per CLI + health checks + output normalizers
├─ core/platform/ ──── Skills registry, MCP client, vector/file/SQLite memory store
├─ core/research/ ──── Web search + Agent synthesis → project profile + org template
├─ core/rbac/ ──────── Skill/MCP/memory permission resolution along org tree
├─ core/supervisor/ ── Python PortRegistry/ProcessRegistry (Go gRPC daemon optional)
├─ platform/mcp/ ───── MCP stdio gateway: JSON-RPC connection pool + process lifecycle
├─ platform/memory/ ── Persistent memory store (file / SQLite FTS5 / ChromaDB vector)
├─ supervisor/ ─────── Go gRPC daemon (optional; Python fallback in core/supervisor/)
└─ config/ ─────────── YAML: agents.yaml, platform.yaml, agents_catalog.yaml, templates/
```

### Agent Adapters

Each agent CLI has a dedicated adapter class in [agents/adapters.py](agents/adapters.py):

| Adapter | Command | Headless flags | Interactive flags |
|---------|---------|---------------|-------------------|
| `ClaudeCodeAdapter` | `claude` | `-p --dangerously-skip-permissions` | `--dangerously-skip-permissions` |
| `OpenCodeAdapter` | `opencode` | `run --format json` | `--model deepseek/deepseek-chat` |
| `HermesAdapter` | `hermes` | `chat -q` | `chat --tui` |
| `AiderAdapter` | `aider` | `--message --yes` | `--model deepseek/deepseek-chat --yes` |
| `GooseAdapter` | `goose` | `run --yes` | `session --yes` |
| `CodexAdapter` | `codex` | `exec` | (none) |
| `GeminiCLIAdapter` | `gemini` | `-p` | (none) |

All adapters implement `BaseAgentAdapter` with `build_command()` (headless capture) and `build_interactive_command()` (TUI terminal). The registry maps `command` → adapter class; unknown commands fall back to `ClaudeCodeAdapter`.

Key execution paths:
- **Headless capture**: `agents/runner.py` → `build_command()` → `subprocess.run(cmd, capture_output=True)` — used for manager decomposition and research. Has timeout, retry, and truncated-JSON repair.
- **Interactive (TUI)**: `core/terminal/agent_launcher.py` → `build_interactive_command()` → `spawn_agent_terminal()` — opens a new Windows Terminal tab.
- **Worker watch mode**: `cli/agent_worker.py cmd_watch` — inbox polling (5s), PID file registration, shared worktree reuse. Supports graceful shutdown.
- **Windows shim resolution**: `agents/execute.py` `prepare_subprocess_argv()` handles `.cmd`/`.bat`/`.ps1` npm shims → native `.exe` or `node` scripts.

### Task Lifecycle (File-Driven State Machine)

```
pending → assigned → in_progress → submitted → in_review → approved/archived
                                                         → rejected → in_progress
                                                         → escalated (CEO decision)
            blocked (waits_on dependencies not met)
```

State stored as YAML in `tasks/active/{task_id}.yaml`. Inter-agent messages via JSON files in `agents/{id}/inbox/`; `MessageBus` drains by renaming `.json` → `processed/`.

### Orchestration Flow (v0.2.0 — full loop closed)

1. `studio task "..." --orchestrate` → `Dispatcher.create_task()` writes root task + inbox message to manager
2. Manager decomposes; output parsed from `---STUDIO_SUBTASKS_JSON---` marker with retry + truncated-JSON repair
3. `apply_subtasks()` writes child task YAMLs, spawns worker terminals via `spawn_worker_agent_terminal()`
4. Workers write `.studio/DELIVER.json` when done; polling detects and triggers manager review
5. Manager reviews and outputs verdict JSON after `---STUDIO_REVIEW_JSON---`
6. `compute_orchestration_progress()` tracks 6 stages (create→decompose→spawn→deliver→review→archive) with dynamic percentages

### Key Systems (all completed in v0.2.0)

- **ChromaDB vector memory** (`core/platform/vector_memory.py`): Hybrid search (vector + keyword RRF fusion), ONNX embeddings, graceful degradation to SQLite FTS5
- **MCP stdio gateway** (`platform/mcp/gateway/`): JSON-RPC 2.0 connection pool, subprocess lifecycle management, tool call timeout (60s), health-check pings
- **Agent health checks** (`agents/health.py`): 3-stage pipeline (PATH→--version→smoke test) with timeout detection and API-key-error classification
- **Agent session persistence** (`cli/agent_worker.py cmd_watch`): Inbox polling + PID registration + shared worktree reuse across sessions
- **Org expansion** (`core/org/expand_ops.py`): Research-driven business line expansion, role insertion, manager layer insertion
- **Config policy** (`core/config/agent_policy.py`): BYOK enforcement, enable/disable toggles, 30s caching, auto-detect installed agents

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
- **Decompose resilience**: Retry-on-parse-failure with error feedback to manager, truncated-JSON repair, markdown fence stripping. Fallback controlled by `platform.yaml` (`decompose_fallback: mock|raise`)
- **Adaptive timeouts**: Per-task-type timeouts from `platform.yaml` (`orchestration.timeout_decompose|research|review|agent`), defaults: decompose 300s, research 180s, others 120s
