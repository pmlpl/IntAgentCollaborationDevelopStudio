# Phase 1 最小闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 跑通 `studio init` → `studio task` → `studio status` → `studio review` 最小闭环，含 Go Supervisor（进程/端口/锁）、组织树、inbox 消息、Git Worktree 隔离。

**Architecture:** Go Supervisor 守护 `.studio/` 原子状态并通过 gRPC 暴露锁/端口/spawn API；Python 业务层处理 CLI、组织树、任务 FSM、消息 inbox、Worktree；Agent 适配层 subprocess 调用外部 CLI。

**Tech Stack:** Go 1.22+, Python 3.11, gRPC, PyYAML, questionary, Git Worktree, pytest

**Spec:** [2026-06-07-local-multi-agent-platform-design.md](../specs/2026-06-07-local-multi-agent-platform-design.md)

---

## 文件结构概览

| 路径 | 职责 |
|---|---|
| `supervisor/cmd/studio-supervisor/main.go` | Go 守护进程入口 |
| `supervisor/pkg/lock/filelock.go` | 跨平台文件锁 |
| `supervisor/pkg/lock/portlease.go` | 端口租约注册表 |
| `supervisor/pkg/process/registry.go` | 进程 PID 注册 |
| `supervisor/api/supervisor.proto` | gRPC 接口定义 |
| `core/org/tree_ops.py` | 组织树 CRUD |
| `core/org/org_chart.py` | 树形渲染（CLI 用） |
| `core/ipc/message_bus.py` | inbox 读写 |
| `core/dispatch/task_fsm.py` | 任务状态机 |
| `core/dispatch/dispatcher.py` | 任务路由与下发 |
| `core/workspace/worktree.py` | Git Worktree 管理 |
| `core/supervisor_client.py` | Python gRPC 客户端 |
| `agents/base.py` | Agent 适配抽象基类 |
| `agents/claude_code.py` | Claude Code subprocess 适配 |
| `cli/studio.py` | CLI 入口与子命令 |
| `config/agents.yaml` | Agent 注册表 |
| `config/models.yaml` | 模型注册表 |

---

### Task 1: 项目脚手架与目录结构

**Files:**
- Create: `pyproject.toml`
- Create: `supervisor/go.mod`
- Create: `.gitignore`
- Create: `config/agents.yaml`
- Create: `config/models.yaml`
- Create: `config/platform.yaml`
- Test: `tests/test_scaffold.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scaffold.py
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_required_directories_exist():
    dirs = [
        "config", "core", "agents", "cli", "supervisor",
        "platform/memory", "platform/skills", "platform/mcp",
        "docs/superpowers/specs", "docs/superpowers/plans",
    ]
    for d in dirs:
        assert (ROOT / d).is_dir(), f"missing directory: {d}"

def test_config_files_exist():
    assert (ROOT / "config" / "agents.yaml").is_file()
    assert (ROOT / "config" / "models.yaml").is_file()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scaffold.py -v`  
Expected: FAIL — directories/files not found

- [ ] **Step 3: Create scaffold**

`pyproject.toml`:
```toml
[project]
name = "int-agent-studio"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "pyyaml>=6.0",
    "questionary>=2.0",
    "grpcio>=1.60",
    "protobuf>=4.25",
]

[project.scripts]
studio = "cli.studio:main"

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

`.gitignore`:
```
.studio/
projects/
__pycache__/
*.pyc
.venv/
supervisor/bin/
platform/memory/store/
*.egg-info/
```

`config/agents.yaml` — 复制 AGENTS.md 中的 agents 注册表内容。

`config/models.yaml` — 复制 AGENTS.md 中的 models 注册表内容。

`config/platform.yaml`:
```yaml
supervisor:
  port_range: [41000, 41999]
  lock_timeout_sec: 30
  pipe_name: "\\\\.\\pipe\\studio-supervisor"
memory:
  enabled: false  # Phase 2
skills:
  registry_path: platform/skills/registry.yaml
mcp:
  gateway_enabled: false  # Phase 2
```

创建所有空目录（含 `__init__.py` 在 `core/`, `agents/`, `cli/` 子包）。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_scaffold.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```powershell
git init
git add .
git commit -m "chore: scaffold project directory structure and config"
```

---

### Task 2: 组织树 — tree_ops

**Files:**
- Create: `core/org/__init__.py`
- Create: `core/org/tree_ops.py`
- Test: `tests/core/org/test_tree_ops.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/org/test_tree_ops.py
import pytest
from core.org.tree_ops import OrgTree, OrgTreeError

SAMPLE = [
    {"id": "laowang", "name": "老王", "parent": None, "is_manager": True},
    {"id": "xiaohong", "name": "小红", "parent": "laowang"},
    {"id": "dazhuang", "name": "大壮", "parent": "laowang"},
]

def test_subtree_returns_descendants():
    tree = OrgTree(SAMPLE)
    assert set(tree.subtree("laowang")) == {"laowang", "xiaohong", "dazhuang"}

def test_subtree_leaf_is_self_only():
    tree = OrgTree(SAMPLE)
    assert tree.subtree("xiaohong") == ["xiaohong"]

def test_move_subtree_rejects_cycle():
    tree = OrgTree(SAMPLE)
    with pytest.raises(OrgTreeError, match="cycle"):
        tree.move_subtree("laowang", "xiaohong")

def test_add_node_under_parent():
    tree = OrgTree(SAMPLE)
    tree.add_node("laowang", {"id": "xiaoyan", "name": "小严", "parent": "laowang"})
    assert "xiaoyan" in tree.subtree("laowang")

def test_ancestors():
    tree = OrgTree(SAMPLE)
    assert tree.ancestors("xiaohong") == ["laowang"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/core/org/test_tree_ops.py -v`  
Expected: FAIL — `OrgTree` not defined

- [ ] **Step 3: Implement tree_ops.py**

```python
# core/org/tree_ops.py
from __future__ import annotations
from copy import deepcopy
from typing import Any


class OrgTreeError(Exception):
    pass


class OrgTree:
    def __init__(self, positions: list[dict[str, Any]]):
        self._positions = {p["id"]: deepcopy(p) for p in positions}
        self._validate()

    def _validate(self) -> None:
        for pid, pos in self._positions.items():
            parent = pos.get("parent")
            if parent is not None and parent not in self._positions:
                raise OrgTreeError(f"unknown parent {parent!r} for {pid!r}")
        if self._has_cycle():
            raise OrgTreeError("cycle detected in org tree")

    def _has_cycle(self) -> bool:
        visited: set[str] = set()
        for pid in self._positions:
            seen: set[str] = set()
            cur: str | None = pid
            while cur is not None:
                if cur in seen:
                    return True
                seen.add(cur)
                cur = self._positions[cur].get("parent")
        return False

    def subtree(self, node_id: str) -> list[str]:
        if node_id not in self._positions:
            raise OrgTreeError(f"unknown node {node_id!r}")
        result = [node_id]
        for pid, pos in self._positions.items():
            if pid != node_id and self._is_descendant(pid, node_id):
                result.append(pid)
        return result

    def _is_descendant(self, node_id: str, ancestor_id: str) -> bool:
        cur = self._positions[node_id].get("parent")
        while cur is not None:
            if cur == ancestor_id:
                return True
            cur = self._positions[cur].get("parent")
        return False

    def ancestors(self, node_id: str) -> list[str]:
        if node_id not in self._positions:
            raise OrgTreeError(f"unknown node {node_id!r}")
        chain: list[str] = []
        cur = self._positions[node_id].get("parent")
        while cur is not None:
            chain.append(cur)
            cur = self._positions[cur].get("parent")
        return chain

    def add_node(self, parent_id: str, spec: dict[str, Any]) -> None:
        if parent_id not in self._positions:
            raise OrgTreeError(f"unknown parent {parent_id!r}")
        nid = spec["id"]
        if nid in self._positions:
            raise OrgTreeError(f"duplicate id {nid!r}")
        spec = deepcopy(spec)
        spec["parent"] = parent_id
        self._positions[nid] = spec
        self._validate()

    def move_subtree(self, node_id: str, new_parent_id: str) -> None:
        if node_id not in self._positions:
            raise OrgTreeError(f"unknown node {node_id!r}")
        if new_parent_id not in self._positions:
            raise OrgTreeError(f"unknown parent {new_parent_id!r}")
        if new_parent_id in self.subtree(node_id):
            raise OrgTreeError("cycle: cannot move node under its descendant")
        self._positions[node_id]["parent"] = new_parent_id
        self._validate()

    def to_list(self) -> list[dict[str, Any]]:
        return list(self._positions.values())

    @classmethod
    def from_yaml_data(cls, data: dict) -> OrgTree:
        return cls(data.get("positions", []))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/core/org/test_tree_ops.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```powershell
git add core/org/ tests/core/
git commit -m "feat: add org tree operations with cycle detection"
```

---

### Task 3: 消息 Inbox — message_bus

**Files:**
- Create: `core/ipc/__init__.py`
- Create: `core/ipc/message_bus.py`
- Test: `tests/core/ipc/test_message_bus.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/ipc/test_message_bus.py
import json
from pathlib import Path
from core.ipc.message_bus import MessageBus, Message

def test_deliver_and_drain(tmp_path: Path):
    inbox = tmp_path / "inbox"
    bus = MessageBus(inbox)
    msg = Message(
        id="msg-001",
        type="task_assign",
        sender="laowang",
        recipient="dazhuang",
        task_id="task-001",
        payload={"description": "写 API"},
    )
    bus.deliver(msg)
    assert (inbox / "msg-001.json").exists()
    drained = bus.drain()
    assert len(drained) == 1
    assert drained[0].payload["description"] == "写 API"
    assert not (inbox / "msg-001.json").exists()
    assert (inbox / "processed" / "msg-001.json").exists()
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `pytest tests/core/ipc/test_message_bus.py -v`

- [ ] **Step 3: Implement message_bus.py**

```python
# core/ipc/message_bus.py
from __future__ import annotations
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class Message:
    id: str
    type: str
    sender: str
    recipient: str
    task_id: str
    payload: dict[str, Any]
    trace: list[str] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class MessageBus:
    def __init__(self, inbox_dir: Path):
        self.inbox_dir = inbox_dir
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        (self.inbox_dir / "processed").mkdir(exist_ok=True)

    def _to_json_dict(self, msg: Message) -> dict:
        d = asdict(msg)
        d["from"] = d.pop("sender")
        d["to"] = d.pop("recipient")
        return d

    def _from_json_dict(self, data: dict) -> Message:
        data = dict(data)
        data["sender"] = data.pop("from")
        data["recipient"] = data.pop("to")
        return Message(**data)

    def deliver(self, msg: Message) -> Path:
        path = self.inbox_dir / f"{msg.id}.json"
        path.write_text(json.dumps(self._to_json_dict(msg), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def drain(self) -> list[Message]:
        messages: list[Message] = []
        for path in sorted(self.inbox_dir.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            messages.append(self._from_json_dict(data))
            processed = self.inbox_dir / "processed" / path.name
            path.rename(processed)
        return messages
```

- [ ] **Step 4: Run test — expect PASS**

Run: `pytest tests/core/ipc/test_message_bus.py -v`

- [ ] **Step 5: Commit**

```powershell
git add core/ipc/ tests/core/ipc/
git commit -m "feat: add file-based message inbox bus"
```

---

### Task 4: 任务状态机 — task_fsm

**Files:**
- Create: `core/dispatch/__init__.py`
- Create: `core/dispatch/task_fsm.py`
- Test: `tests/core/dispatch/test_task_fsm.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/dispatch/test_task_fsm.py
import pytest
from core.dispatch.task_fsm import TaskFSM, InvalidTransition

def test_pending_to_assigned():
    fsm = TaskFSM("pending")
    fsm.transition("assigned")
    assert fsm.state == "assigned"

def test_blocked_auto_unblock():
    fsm = TaskFSM("blocked")
    fsm.transition("assigned")
    assert fsm.state == "assigned"

def test_invalid_transition_raises():
    fsm = TaskFSM("pending")
    with pytest.raises(InvalidTransition):
        fsm.transition("approved")
```

- [ ] **Step 2: Run test — expect FAIL**

- [ ] **Step 3: Implement task_fsm.py**

```python
# core/dispatch/task_fsm.py
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
    pass


class TaskFSM:
    def __init__(self, initial: str = "pending"):
        if initial not in VALID_TRANSITIONS and initial != "archived":
            raise InvalidTransition(f"unknown state: {initial}")
        self.state = initial

    def transition(self, target: str) -> None:
        allowed = VALID_TRANSITIONS.get(self.state, set())
        if target not in allowed and not (self.state == "archived" and target == "archived"):
            raise InvalidTransition(f"cannot go from {self.state!r} to {target!r}")
        self.state = target

    def can_transition(self, target: str) -> bool:
        return target in VALID_TRANSITIONS.get(self.state, set())
```

- [ ] **Step 4: Run test — expect PASS**

- [ ] **Step 5: Commit**

```powershell
git add core/dispatch/task_fsm.py tests/core/dispatch/
git commit -m "feat: add task lifecycle state machine"
```

---

### Task 5: Git Worktree — worktree

**Files:**
- Create: `core/workspace/__init__.py`
- Create: `core/workspace/worktree.py`
- Test: `tests/core/workspace/test_worktree.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/workspace/test_worktree.py
import subprocess
from pathlib import Path
from core.workspace.worktree import WorktreeManager

def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)

def test_create_and_remove_worktree(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@test.com")
    _git(repo, "config", "user.name", "test")
    (repo / "README.md").write_text("# test", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init")

    ws_root = tmp_path / "workspaces"
    mgr = WorktreeManager(repo, ws_root)
    path = mgr.create("task-001", "search-ui")
    assert path.is_dir()
    assert (path / "README.md").exists()
    mgr.remove("task-001-search-ui")
    assert not path.exists()
```

- [ ] **Step 2: Run test — expect FAIL**

- [ ] **Step 3: Implement worktree.py**

```python
# core/workspace/worktree.py
from __future__ import annotations
import subprocess
from pathlib import Path


class WorktreeError(Exception):
    pass


class WorktreeManager:
    def __init__(self, repo_path: Path, workspaces_root: Path):
        self.repo_path = repo_path.resolve()
        self.workspaces_root = workspaces_root.resolve()
        self.workspaces_root.mkdir(parents=True, exist_ok=True)

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=self.repo_path,
            check=True,
            capture_output=True,
            text=True,
        )

    def create(self, task_id: str, slug: str) -> Path:
        branch = f"studio/{task_id}-{slug}"
        dest = self.workspaces_root / f"{task_id}-{slug}"
        if dest.exists():
            raise WorktreeError(f"worktree already exists: {dest}")
        self._run("branch", branch, "HEAD")
        self._run("worktree", "add", str(dest), branch)
        return dest

    def remove(self, worktree_name: str) -> None:
        dest = self.workspaces_root / worktree_name
        if not dest.exists():
            raise WorktreeError(f"worktree not found: {dest}")
        branch = self._run("worktree", "list", "--porcelain").stdout
        self._run("worktree", "remove", str(dest), "--force")
        # 清理 branch: studio/{task_id}-{slug}
        branch_name = f"studio/{worktree_name}"
        subprocess.run(
            ["git", "branch", "-D", branch_name],
            cwd=self.repo_path,
            capture_output=True,
        )
```

- [ ] **Step 4: Run test — expect PASS**

Run: `pytest tests/core/workspace/test_worktree.py -v`

- [ ] **Step 5: Commit**

```powershell
git add core/workspace/ tests/core/workspace/
git commit -m "feat: add git worktree manager for agent isolation"
```

---

### Task 6: Go Supervisor — 端口租约与 PID 注册

**Files:**
- Create: `supervisor/go.mod`
- Create: `supervisor/pkg/lock/portlease.go`
- Create: `supervisor/pkg/process/registry.go`
- Create: `supervisor/pkg/lock/portlease_test.go`
- Test: `supervisor/pkg/lock/portlease_test.go`

- [ ] **Step 1: Write the failing test**

```go
// supervisor/pkg/lock/portlease_test.go
package lock

import (
    "os"
    "path/filepath"
    "testing"
)

func TestPortLeaseAcquireRelease(t *testing.T) {
    dir := t.TempDir()
    reg := NewPortRegistry(filepath.Join(dir, "ports.json"), 41000, 41010)
    port, err := reg.Acquire("agent-a")
    if err != nil {
        t.Fatal(err)
    }
    if port < 41000 || port > 41010 {
        t.Fatalf("port out of range: %d", port)
    }
    if err := reg.Release(port); err != nil {
        t.Fatal(err)
    }
    port2, err := reg.Acquire("agent-b")
    if err != nil {
        t.Fatal(err)
    }
    if port2 == 0 {
        t.Fatal("expected port after release")
    }
}
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `cd supervisor && go test ./pkg/lock/... -v`

- [ ] **Step 3: Implement portlease.go and registry.go**

`portlease.go` 核心逻辑：JSON 文件 + sync.Mutex；`Acquire` 扫描 range 找空闲 port；`Release` 删除 entry；写文件前 flock。

`registry.go`：`Register(positionID, pid)` / `Unregister(positionID)` / `IsAlive(positionID)` 检查 os.FindProcess + Signal(0)。

- [ ] **Step 4: Run test — expect PASS**

- [ ] **Step 5: Commit**

```powershell
git add supervisor/
git commit -m "feat: add Go port lease registry and process registry"
```

---

### Task 7: Go Supervisor — gRPC 服务

**Files:**
- Create: `supervisor/api/supervisor.proto`
- Create: `supervisor/cmd/studio-supervisor/main.go`
- Create: `core/supervisor_client.py`
- Test: `tests/test_supervisor_client.py`（可选 mock；集成测试手动）

- [ ] **Step 1: Define proto**

```protobuf
syntax = "proto3";
package supervisor;
option go_package = "studio/supervisor/api";

service Supervisor {
  rpc Health(HealthRequest) returns (HealthResponse);
  rpc AcquirePort(AcquirePortRequest) returns (AcquirePortResponse);
  rpc ReleasePort(ReleasePortRequest) returns (ReleasePortResponse);
  rpc SpawnAgent(SpawnAgentRequest) returns (SpawnAgentResponse);
  rpc KillAgent(KillAgentRequest) returns (KillAgentResponse);
}

message HealthRequest {}
message HealthResponse { bool ok = 1; }

message AcquirePortRequest { string owner = 1; }
message AcquirePortResponse { int32 port = 1; }

message ReleasePortRequest { int32 port = 1; }
message ReleasePortResponse { bool ok = 1; }

message SpawnAgentRequest {
  string position_id = 1;
  string project_id = 2;
  string worktree_path = 3;
  repeated string command = 4;
  map<string, string> env = 5;
}
message SpawnAgentResponse { int32 pid = 1; }

message KillAgentRequest { string position_id = 1; }
message KillAgentResponse { bool ok = 1; }
```

- [ ] **Step 2: Implement main.go**

- 启动时创建 `.studio/registry/` 目录
- 写 `.studio/supervisor.pid`
- Windows Named Pipe listener（可用 `net.Listen("tcp", "127.0.0.1:42000")` 作为 Phase 1 简化，文档注明 Phase 1.1 改 Named Pipe）
- 注册 gRPC 服务

- [ ] **Step 3: Python client stub**

```python
# core/supervisor_client.py
import grpc
from pathlib import Path

# 生成 stub: python -m grpc_tools.protoc ...
class SupervisorClient:
    def __init__(self, address: str = "127.0.0.1:42000"):
        self.address = address
        self._channel = None

    def ensure_running(self, root: Path) -> None:
        pid_file = root / ".studio" / "supervisor.pid"
        if pid_file.exists():
            return
        # spawn supervisor binary
        import subprocess
        bin_path = root / "supervisor" / "bin" / "studio-supervisor.exe"
        subprocess.Popen([str(bin_path), "--root", str(root)], cwd=root)

    def health(self) -> bool:
        # call Health RPC
        ...
```

- [ ] **Step 4: Build supervisor**

Run: `cd supervisor && go build -o bin/studio-supervisor.exe ./cmd/studio-supervisor`

- [ ] **Step 5: Commit**

```powershell
git add supervisor/ core/supervisor_client.py
git commit -m "feat: add Go supervisor gRPC service skeleton"
```

---

### Task 8: Agent 适配层 — base + claude_code

**Files:**
- Create: `agents/base.py`
- Create: `agents/claude_code.py`
- Create: `agents/registry.py`
- Test: `tests/agents/test_base.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/agents/test_base.py
from agents.registry import load_agent_config, build_command

def test_build_command_claude_code():
    cfg = {"command": "claude", "flags": "-p"}
    cmd = build_command(cfg, task="hello", worktree="/tmp/wt")
    assert cmd[0] == "claude"
    assert "-p" in cmd
    assert "hello" in cmd
```

- [ ] **Step 2: Implement agents/base.py and registry.py**

```python
# agents/base.py
from abc import ABC, abstractmethod
from pathlib import Path
from dataclasses import dataclass

@dataclass
class AgentRunContext:
    task: str
    worktree: Path
    skills: list[str]
    mcp_servers: list[str]
    env: dict[str, str]

class BaseAgentAdapter(ABC):
    @abstractmethod
    def build_command(self, ctx: AgentRunContext) -> list[str]:
        ...

    @abstractmethod
    def run(self, ctx: AgentRunContext) -> int:
        ...
```

```python
# agents/claude_code.py
import subprocess
from agents.base import AgentRunContext, BaseAgentAdapter

class ClaudeCodeAdapter(BaseAgentAdapter):
    def __init__(self, command: str = "claude", flags: str = "-p"):
        self.command = command
        self.flags = flags.split()

    def build_command(self, ctx: AgentRunContext) -> list[str]:
        return [self.command, *self.flags, ctx.task]

    def run(self, ctx: AgentRunContext) -> int:
        cmd = self.build_command(ctx)
        result = subprocess.run(cmd, cwd=ctx.worktree, env=ctx.env)
        return result.returncode
```

- [ ] **Step 3: Run test — expect PASS**

- [ ] **Step 4: Commit**

```powershell
git add agents/ tests/agents/
git commit -m "feat: add agent adapter base and Claude Code adapter"
```

---

### Task 9: Dispatcher 骨架

**Files:**
- Create: `core/dispatch/dispatcher.py`
- Create: `core/project.py`
- Test: `tests/core/dispatch/test_dispatcher.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/dispatch/test_dispatcher.py
from pathlib import Path
import yaml
from core.dispatch.dispatcher import Dispatcher

def test_create_root_task(tmp_path: Path):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    positions = {
        "project": "test",
        "positions": [
            {"id": "laowang", "name": "老王", "parent": None, "is_manager": True, "agent": "claude-code", "model": "deepseek-v4-pro"},
        ],
    }
    (project_dir / "positions.yaml").write_text(yaml.dump(positions, allow_unicode=True), encoding="utf-8")
    (project_dir / "agents" / "laowang" / "inbox").mkdir(parents=True)

    disp = Dispatcher(project_dir)
    task = disp.create_task("加个搜索框")
    assert task["status"] == "pending"
    inbox_files = list((project_dir / "agents" / "laowang" / "inbox").glob("*.json"))
    assert len(inbox_files) == 1
```

- [ ] **Step 2: Implement dispatcher.py**

核心方法：
- `create_task(description)` → 写 `tasks/active/{task-id}.yaml`，发 `task_decompose` 到 root manager inbox
- `get_status()` → 读所有 active tasks + agent runtime state
- `submit_review(task_id, verdict)` → 处理 approved/rejected/escalated

- [ ] **Step 3: Run test — expect PASS**

- [ ] **Step 4: Commit**

```powershell
git add core/dispatch/dispatcher.py core/project.py tests/core/dispatch/
git commit -m "feat: add dispatcher skeleton for task creation and routing"
```

---

### Task 10: CLI — studio init / task / status / review

**Files:**
- Create: `cli/studio.py`
- Create: `core/project.py`（init 逻辑）
- Test: `tests/cli/test_studio_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/cli/test_studio_cli.py
from click.testing import CliRunner
# 若不用 click，用 argparse + 直接调用 main(["init", ...])

def test_studio_init_creates_project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from cli.studio import main
    # 模拟 questionary 输入：项目名 + 确认默认 positions
    ...
```

Phase 1 可简化为 `studio init --name todo --template manual` 跳过交互式调研。

- [ ] **Step 2: Implement cli/studio.py**

子命令：
- `studio init --name <project> [--repo <path>]` — 创建 `projects/{name}/positions.yaml` 和目录结构
- `studio task "<description>"` — 调用 Dispatcher.create_task
- `studio status` — 打印任务和 Agent 进度
- `studio review` — 列出待 CEO 审批项

使用 `argparse` + `questionary`（交互模式）。

- [ ] **Step 3: Manual smoke test**

```powershell
pip install -e .
studio init --name demo --repo .
studio task "创建 README"
studio status
studio review
```

- [ ] **Step 4: Commit**

```powershell
git add cli/ core/project.py tests/cli/
git commit -m "feat: add studio CLI with init, task, status, review commands"
```

---

### Task 11: 集成验证 — 最小闭环

**Files:**
- Create: `tests/integration/test_minimal_loop.py`

- [ ] **Step 1: Integration test (mock agent)**

用 `echo` 或 mock adapter 代替真实 Claude Code，验证：
1. init 创建项目结构
2. task 创建任务 + inbox 消息
3. status 可读任务状态
4. worktree 创建成功

- [ ] **Step 2: Run full test suite**

Run: `pytest tests/ -v`  
Expected: ALL PASS

- [ ] **Step 3: Update AGENTS.md 项目结构节**

同步实际目录与 CLI 用法。

- [ ] **Step 4: Final commit**

```powershell
git add .
git commit -m "test: add integration test for minimal studio loop"
```

---

## Plan Self-Review

**Spec 覆盖：**
- 单根目录结构 → Task 1 scaffold
- 防冲突（端口/进程/文件） → Task 6, 7
- 组织树 → Task 2
- 消息流转 → Task 3, 9
- Git Worktree → Task 5
- Agent 适配 → Task 8
- CLI 闭环 → Task 10, 11
- 记忆/Skills/MCP 中台 → Phase 2（spec 第 7 节），本计划不含

**Placeholder 扫描：** 无 TBD；Task 7 Python client 的 `...` 在实现时需补全 gRPC stub 生成步骤。

**类型一致性：** `Message.sender/recipient` 与 spec `from/to` 在 JSON 序列化时用 `asdict`——实现 Task 3 时需统一字段名为 spec 的 `from`/`to`（Python 保留字，JSON 用 `"from"`/`"to"`，dataclass 用 `sender`/`recipient` 并在 `to_dict()` 中映射）。

---

## 执行选项

Plan 已保存。两种执行方式：

1. **Subagent-Driven（推荐）** — 每个 Task 派一个子 Agent，任务间 Review
2. **Inline Execution** — 本会话按 Task 顺序逐步执行，检查点 Review

请选择执行方式。
