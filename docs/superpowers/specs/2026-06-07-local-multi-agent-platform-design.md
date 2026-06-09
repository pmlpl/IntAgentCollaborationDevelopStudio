# 本地多 Agent 管理平台架构设计

**日期：** 2026-06-07  
**状态：** 已批准  
**关联文档：** [AGENTS.md](../../../AGENTS.md)

---

## 1. 产品定位

IntAgentCollaborationDevelopStudio 是一款 **CEO 模式本地多 Agent 编排平台**。用户下达业务目标，系统调研并生成组织树，主管 Agent 拆解任务，Worker 在 Git Worktree 隔离环境中并行开发，审查通过后合并代码。

**Agent 运行时形态：** 混合编排器——平台内置 Go Supervisor + Python 业务层；Agent Worker 为外部终端 CLI（Claude Code / Hermes / OpenCode），通过 subprocess 适配层调用。Cursor 等 IDE 用于人工编辑与本平台开发，不作为编排 Worker。

### 1.1 与 AGENTS.md 的关系

| AGENTS.md 既定 | 本设计扩展 |
|---|---|
| 编排器 + subprocess | Go 调度守护进程统一管理进程/端口/锁 |
| YAML 配置、无 DB | YAML 管组织/任务；向量库仅用于记忆中台（嵌入式 ChromaDB） |
| 纯 CLI | CLI 树形组织编辑（`studio org`），暂不做 Web UI |
| Git Worktree 代码隔离 | Agent 运行时全维度隔离（文件/端口/缓存/日志） |
| resume.skills / mcp_servers | 全局中台 + 层级 RBAC |

---

## 2. 单根目录结构

所有组件统一存放在项目根 `IntAgentCollaborationDevelopStudio/`，不设立第二级平台根目录。

```
IntAgentCollaborationDevelopStudio/          # 唯一根目录
│
├── .studio/                                 # 【平台运行时】不可手改，原子状态
│   ├── supervisor.pid                       # Go 守护进程 PID
│   ├── registry/
│   │   ├── ports.json                       # 端口租约表 {port: {owner, expires}}
│   │   ├── processes.json                   # 进程注册表 {position_id: {pid, started_at}}
│   │   └── locks/                           # 文件锁桩目录 (*.lock 由 flock 创建)
│   ├── ipc/
│   │   └── bus.sock                         # 本地消息总线 (Windows: \\.\pipe\studio-bus)
│   └── state/
│       └── platform.version
│
├── config/                                  # 【系统共享配置】
│   ├── agents.yaml                          # Agent 注册表
│   ├── models.yaml                          # 模型注册表
│   ├── platform.yaml                        # 中台全局配置
│   └── templates/                           # 调研模板存档
│
├── platform/                                # 【全局中台 - 共享资源层】
│   ├── memory/
│   │   ├── store/                           # ChromaDB 向量库持久化
│   │   ├── index.meta                       # 命名空间索引
│   │   └── acl/                             # 记忆 ACL 规则缓存
│   ├── skills/
│   │   ├── registry.yaml                    # 技能元数据注册表
│   │   ├── packages/                        # 技能包实体
│   │   └── manifests/                       # 版本与依赖声明
│   └── mcp/
│       ├── registry.yaml                    # MCP 服务注册
│       ├── pool/                            # 连接池状态
│       └── gateway/                         # MCP 网关进程配置
│
├── core/                                    # 【Python 业务核心】
│   ├── org/          org_chart.py, tree_ops.py
│   ├── rbac/         permission.py, inherit.py
│   ├── dispatch/     dispatcher.py, task_fsm.py
│   ├── workspace/    worktree.py
│   ├── platform/     memory_client.py, skills_client.py, mcp_client.py
│   └── ipc/          message_bus.py
│
├── supervisor/                              # 【Go 调度层】
│   ├── cmd/studio-supervisor/
│   ├── pkg/lock/     filelock + portlease
│   ├── pkg/process/  spawn/monitor/kill
│   └── pkg/ipc/      gRPC over UDS/named pipe
│
├── agents/                                  # 【Agent 适配层】
│   ├── base.py
│   ├── claude_code.py, hermes.py, opencode.py
│
├── cli/
│   └── studio.py                            # CLI 主入口
│
└── projects/                                # 【项目实例区】（不提交 Git）
    └── {project-id}/
        ├── positions.yaml                   # 组织树
        ├── permissions.yaml                 # 项目级 RBAC 覆盖（可选）
        ├── org.snapshot.yaml                # 组织变更审计快照
        ├── shared/
        │   └── task-graph.yaml              # 依赖链定义
        ├── agents/                          # 【各 Agent 私有沙箱】
        │   └── {position-id}/
        │       ├── runtime/
        │       │   ├── state.json
        │       │   ├── lease.port
        │       │   └── env.local
        │       ├── cache/
        │       ├── logs/
        │       │   └── {task-id}.log
        │       └── inbox/
        │           └── {msg-id}.json
        ├── tasks/
        │   ├── active/
        │   └── archive/
        └── workspaces/                      # Git Worktree
            └── {task-id}-{slug}/
```

### 2.1 分区原则

- **全局共享：** `config/`、`platform/`——所有项目共用记忆/Skills/MCP
- **项目共享：** `projects/{id}/shared/`、`positions.yaml`
- **Agent 私有：** `projects/{id}/agents/{position-id}/`——Agent 只读写自己的 subtree
- **代码隔离：** `workspaces/{task-id}/`——Git Worktree，一 task 一 worktree
- **平台原子状态：** `.studio/`——仅 Supervisor 写入，带文件锁

---

## 3. 多 Agent 防冲突方案

### 3.1 隔离矩阵

| 冲突维度 | 机制 | 实现细节 |
|---|---|---|
| 文件读写 | 目录分区 + advisory lock | Agent 只能写 `agents/{self}/` 和分配的 `workspaces/{task}/`；跨区写经平台 API；`.studio/registry/locks/` 用 Go `flock` |
| 端口占用 | 中央租约 | Supervisor 维护 `ports.json`，分配区间 `41000-41999`；租约 TTL + 进程死亡自动回收 |
| 进程 | Supervisor spawn | 每个 position 同时最多 1 个 active worker；`processes.json` 记录 PID，启动前检查 stale PID |
| Git 冲突 | Worktree 隔离 | 一 task 一 worktree branch，合并权仅主管/审查者 |
| MCP 连接 | 连接池 + 会话 ID | Agent 不直连 MCP，走 `platform/mcp/gateway`；请求带 `position_id` 上下文 |
| 记忆写入 | 命名空间 + 写锁 | `memory/{project}/{scope}/{key}` 命名；写操作 acquire namespace lock |

### 3.2 死锁预防

- **锁顺序全局固定：** PlatformLock(1) → ProjectLock(2) → PositionLock(3) → TaskLock(4)，禁止逆序
- **锁超时：** 默认 30s，超时 fail-fast 上报主管
- **无跨 Agent 互锁：** Agent 间通信用单向 inbox 文件队列，不用共享可变状态

### 3.3 Windows 适配

- IPC：Named Pipe（`\\.\pipe\studio-bus`）替代 Unix Domain Socket
- 文件锁：Go Supervisor 统一加锁，Python 通过 gRPC 请求
- 路径：全部相对根目录，禁止 `~/.cursor` 等外部根

---

## 4. 组织架构

### 4.1 数据模型（positions.yaml）

```yaml
positions:
  - id: laowang
    name: 老王
    title: 技术主管
    parent: null
    agent: claude-code
    model: deepseek-v4-pro
    is_manager: true
    resume:
      strengths: [任务拆解, 技术决策]
    permissions:
      memory:  { global: read, project: read_write, subtree: read_write }
      skills:  { use: [fastapi-expert], edit: [] }
      mcp:     { use: [postgres-mcp], configure: [] }

  - id: dazhuang
    name: 大壮
    title: 后端开发
    parent: laowang
    agent: hermes
    model: deepseek-v4-pro
    resume:
      strengths: [REST API, 数据库, 认证]
      skills: [fastapi-expert, python-async]
      mcp_servers: [postgres-mcp]
    waits_on: []
```

### 4.2 树操作 API（core/org/tree_ops.py）

| 方法 | 说明 |
|---|---|
| `add_node(parent_id, spec)` | 新增岗位 |
| `move_subtree(node_id, new_parent_id)` | 换上级（禁止成环） |
| `remove_node(node_id, strategy)` | 删除：`promote_children` / `reassign_to_parent` / `archive` |
| `subtree(node_id)` | 返回子树所有 position id |
| `ancestors(node_id)` | 返回上级链 |

每次变更写入 `org.snapshot.yaml` 审计。

### 4.3 消息模型

```json
{
  "id": "msg-uuid",
  "type": "task_assign | task_result | task_decompose | escalate | status_ping | review_request",
  "from": "laowang",
  "to": "dazhuang",
  "task_id": "task-042",
  "payload": {
    "description": "...",
    "skills_required": ["fastapi-expert"]
  },
  "trace": ["ceo", "laowang"],
  "created_at": "2026-06-07T10:00:00Z"
}
```

- **投递：** 写入 `agents/{to}/inbox/{msg-id}.json`，Supervisor 发 IPC 通知
- **消费：** Agent adapter 启动时 drain inbox，处理后移至 `inbox/processed/`
- **CEO inbox：** `projects/{id}/agents/__ceo__/inbox/`

### 4.4 任务生命周期（FSM）

```
pending → assigned → in_progress → submitted → in_review
  → approved | rejected | escalated → archived
blocked（依赖未完成，自动解除后 → assigned）
```

### 4.5 任务下发流程

1. CEO 执行 `studio task "..."` → Dispatcher 创建根任务
2. 任务投递到 `parent=null` 主管（或用户指定主管）inbox，类型 `task_decompose`
3. 主管 Agent 运行前，平台注入直属+间接下属 resume + RBAC 可见资源
4. 主管输出结构化 JSON：`[{assignee, description, waits_on, skills, mcp}]`
5. Dispatcher 校验 assignee 必须在主管子树内
6. 依赖未满足 → `blocked`；满足 → `task_assign` 投递 Worker inbox
7. Supervisor spawn Worker：分配 worktree + skills manifest + mcp allowlist
8. Worker 提交 → 审查者 inbox `review_request`
9. 审查结果：`approved`（merge worktree）| `rejected`（打回）| `escalated`（CEO inbox）

### 4.6 上报规则

**必须上报 CEO：**
- 架构决策（换技术栈、改数据模型）
- 安全相关（认证、权限、加密）
- 引入新第三方依赖
- Worker 方案不可调和冲突
- 任务超出岗位能力
- 需要新建/拆分岗位

**主管自行处理（事后汇报）：**
- 代码审查通过/打回
- 任务分配和排期
- 技术实现细节选择
- 小的性能优化

---

## 5. 全局三大共享资源

### 5.1 记忆系统中台

| 命名空间 | 用途 | 默认权限 |
|---|---|---|
| `global` | 跨项目通用知识 | 全员 read；CEO write |
| `project/{id}` | 项目上下文 | 项目内 read；主管+相关 worker write |
| `agent/{position_id}` | 个人长期记忆 | 本人 read_write；上级 read；平级不可见 |

- **存储：** 嵌入式 ChromaDB（`platform/memory/store/`）
- **API：** `core/platform/memory_client.py`——`search()`, `upsert()`, `delete()`，内部 RBAC 过滤
- **Hermes 私有记忆：** 仍落 `agents/{id}/cache/`；项目级记忆走中台 API

### 5.2 Skills 技能仓库

```
platform/skills/
├── registry.yaml
└── packages/
    └── fastapi-expert/
        └── SKILL.md
```

- **注册：** `studio skills register ./my-skill`
- **加载（防线一）：** Supervisor 启动 Worker 时，按 RBAC 生成 `agents/{id}/runtime/skills.manifest`，adapter 转 CLI `-s` 参数
- **权限：** `visible`（resume 可见）| `use`（任务注入）| `edit`（修改 packages/）

### 5.3 MCP 网关

```
Agent subprocess → MCP Gateway (platform/mcp/gateway)
                     → postgres-mcp (stdio, 连接池)
                     → browser-mcp
```

- **注册：** `platform/mcp/registry.yaml` + `config/platform.yaml`
- **连接池：** 每种 MCP server 默认 N=1 stdio session，可配置
- **权限：** 请求 `{mcp_id, tool, args}` → Gateway 查 RBAC → 代理 → 审计日志 `agents/{id}/logs/mcp-audit.log`
- **禁止：** Agent 配置中直接写 MCP 启动命令，必须引用 registry id

### 5.4 层级 RBAC

**继承规则（core/rbac/inherit.py）：**

```
有效权限 = 显式 permissions
         ∪ 上级授权（上级 use 的资源，下级默认可 use）
         − 上级 deny 列表
         ∩ 资源全局 ACL
```

| 角色 | memory | skills | mcp |
|---|---|---|---|
| CEO | 全部 read_write | 全部 | 全部 + configure |
| 主管 (is_manager) | 子树 read + project write | 子树 use + 部分 edit | 子树 use |
| Worker | 自身 + project read | resume 声明 use | resume 声明 use |
| 审查者 | project read | 审查相关 use | 测试 MCP use |

权限三元组：`visible | use | edit`（记忆额外有 `delete`）

### 5.5 技能三道防线（AGENTS.md）

| 防线 | 责任方 | 机制 |
|---|---|---|
| 防线一：加载 | 系统 | spawn 时自动注入 skills + MCP |
| 防线二：点名 | 主管 | 任务描述中引用具体技能 |
| 防线三：审查 | 审查者 | 检查代码是否遵守技能规范，违规打回 |

---

## 6. 技术选型

| 层 | 选型 | 理由 |
|---|---|---|
| 调度/锁/端口 | Go 1.22+ | 高并发进程管理、跨平台文件锁 |
| 业务/CLI/适配 | Python 3.11 | 与 AGENTS.md 一致，subprocess 适配成本低 |
| Supervisor↔Python | gRPC over Named Pipe | 强类型、Windows 友好 |
| 消息队列 | 文件 inbox + IPC 通知 | 零依赖、可审计 |
| 记忆向量库 | ChromaDB (embedded) | 本地单目录持久化 |
| 配置 | YAML | 人类可读、可 diff |
| 代码隔离 | Git Worktree | 已有成熟方案 |
| 组织树 | adjacency list + YAML | 简单、可 diff |
| RBAC | 自研 inherit 引擎 | 层级权限定制 |
| 界面 | CLI (questionary) | 零 UI 依赖 |

### 6.1 Supervisor gRPC 接口

```protobuf
service Supervisor {
  rpc AcquirePort(PortRequest) returns (PortLease);
  rpc ReleasePort(PortLease) returns (Empty);
  rpc SpawnAgent(SpawnRequest) returns (ProcessHandle);
  rpc KillAgent(KillRequest) returns (Empty);
  rpc LockPath(LockRequest) returns (LockHandle);
  rpc UnlockPath(LockHandle) returns (Empty);
  rpc Health(Empty) returns (HealthResponse);
}
```

`SpawnRequest` 字段：`position_id`, `project_id`, `worktree_path`, `agent_command`, `skills_manifest`, `mcp_allowlist`, `env`

---

## 7. 实施阶段

### Phase 1 — 最小闭环（优先）

- Supervisor 骨架 + 文件/端口锁
- `studio init` / `task` / `status` / `review`
- positions.yaml 树 + inbox 消息
- Git Worktree

### Phase 2 — 中台与权限

- 记忆/Skills/MCP 注册表 + RBAC
- 三道防线资源注入

### Phase 3 — 扩建与调研

- `studio expand` + web_search 模板
- 组织树动态编辑 CLI（`studio org`）

---

## 8. 设计决策摘要

1. **编排器模式不变**——外部 CLI Agent，平台做 HR + 调度 + 资源中台
2. **单根目录**——`.studio/` 管原子状态，`platform/` 管共享资源，`projects/*/agents/*` 管私有沙箱
3. **Go + Python 双进程**——Go 解决并发安全，Python 保留业务逻辑
4. **RBAC 三层**——global / project / agent namespace，继承上级授权
5. **冲突零容忍**——分区写、中央租约、单向消息、固定锁序
