# IntAgent Collaboration Develop Studio

**CEO 模式本地多 Agent 编排平台。** 你下达业务目标，系统自动调研、拆解任务、在隔离 Git Worktree 中并行调度多个 Agent CLI 干活，审查通过后合并代码。

```
你: "做一个贪吃蛇游戏"
        │
        ▼
┌─ 主管 Agent (Claude Code / Hermes) ─┐
│  拆解: 小红→UI, 大壮→逻辑, 小严→测试   │
└──────────────────────────────────────┘
        │ spawn 并行
  ┌─────┼─────┐
  ▼     ▼     ▼
 小红   大壮   小严       ← 各自独立 Git Worktree
 写完   写完   等待
        │
        ▼
┌─ 主管审查 ─┐
│ 通过 → 合并主分支 │
└─────────────────┘
```

---

## 安装

```bash
git clone https://github.com/pmlpl/IntAgentCollaborationDevelopStudio.git
cd IntAgentCollaborationDevelopStudio
pip install -e ".[dev]"
```

**依赖：** Python 3.11+，Git，至少一个 Agent CLI（Claude Code / Hermes / OpenCode / Aider / Goose / Codex / Gemini CLI）。

若 Agent 未安装，平台会自动降级为 **mock 模式**（规则模拟），可完整演示流程。

---

## 快速开始

```bash
# 创建项目（交互式向导）
studio init --name 我的项目 --description "一个贪吃蛇游戏"

# 下任务 & 编排（mock 模式快速体验）
studio task "做一个终端贪吃蛇游戏" --orchestrate --mock

# 下任务（真实 Agent 驱动）
studio task "做一个终端贪吃蛇游戏" --orchestrate

# 查看状态
studio status

# 查看项目列表
studio project list

# 组织树管理
studio org show
studio org add xiaomo --parent laowang
```

### 启动 TUI 指挥舱

```bash
studio
```

进入全屏 Textual 终端界面：选择项目 → 观察组织树与任务进度 → 下达新任务 → 实时看板。

---

## 架构

```
┌─ cli/studio.py ──── CLI (argparse) + TUI (Textual) 入口
├─ cli/tui/app.py ─── Textual App 全屏指挥舱
├─ core/dispatch/ ─── 任务生命周期: 创建→拆解→派发→审查→合并
├─ core/org/ ──────── 树形组织图 + RBAC 权限继承
├─ core/workspace/ ── Git Worktree 隔离 (一个 Worker 一个环境)
├─ agents/ ────────── 外部 Agent CLI subprocess 适配层
├─ core/platform/ ─── 共享中台: Skills 注册表、MCP 注册表、文件记忆
├─ core/research/ ─── Web 搜索 + Agent 合成 → 项目画像 + 组织模板
└─ supervisor/ ────── Go gRPC 守护进程 (可选，Python fallback)
```

### 任务生命周期

```
pending → assigned → in_progress → submitted → in_review → approved/archived
                                                    → rejected → in_progress
                                                    → escalated (上报CEO)
            blocked (等待依赖)
```

### 三道防线

| 防线 | 时机 | 机制 |
|------|------|------|
| 一 | Agent spawn | Skills/MCP 自动注入 manifest |
| 二 | 主管拆解 | 任务描述中点名应使用的 skills |
| 三 | 主管审查 | 合规清单逐项检查 |

---

## 支持的 Agent CLI

| Agent | 命令 | 自动化标志 |
|-------|------|-----------|
| Claude Code | `claude` | `--dangerously-skip-permissions` |
| Hermes | `hermes` | `--yes` |
| OpenCode | `opencode` | `--yes` |
| Aider | `aider` | `--yes` |
| Goose | `goose` | `--yes` |
| Codex | `codex` | `exec` (天然非交互) |
| Gemini CLI | `gemini` | `-p` (天然非交互) |

---

## 运行测试

```bash
pytest                                    # 全部 164 个测试
pytest -k "research" -v                   # 按模式筛选
pytest --cov=core --cov=agents --cov=cli  # 覆盖率
```

---

## 当前版本: v0.1.0

**已实现：** 项目初始化、任务编排 (mock + 真实)、组织树 CRUD、TUI 指挥舱、Agent 自动化、项目记忆累积、审查过期重试、依赖自动解除。

**下一版本 v0.2.0 将包含：** Agent 会话持久化（inbox watcher 复用终端）、向量记忆检索 (ChromaDB)、MCP Gateway 真实连接池、web_search 真实调研。

---

## 许可

MIT
