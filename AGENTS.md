# IntAgentCollaborationDevelopStudio

多 Agent 协作开发管理平台。

你（CEO）下达命令，系统自动调研项目需要什么岗位、生成公司架构。Agent（Claude Code / Hermes / Cursor / OpenCode / CodeWhale）在 Git Worktree 隔离环境中并行工作，主管 Agent 拆解任务、审查代码、自动合并，只在上报例外情况时找你。

## 核心理念

**你不是项目经理，你是 CEO。** 你不需要知道一个 Web 项目应该有几个岗位、谁应该向谁汇报、任务怎么拆。系统从网上调研，生成推荐架构，你确认即可。日常只收汇报，只在重大决策时介入。

---

## 公司架构：自由生长的树

每个工位就是一个节点，节点记录 `parent` 是谁，树可以长到任意深度。

```
CEO (你)
 └── 老王 (技术主管)               parent: null
       ├── 小红 (前端开发)          parent: laowang
       ├── 大壮 (后端开发)          parent: laowang
       ├── 小严 (测试审查)          parent: laowang
       └── 小新 (小程序主管)         parent: laowang
             ├── 小码 (小程序前端)   parent: xiaoxin   ← 第三层
             └── 小云 (云函数后端)   parent: xiaoxin
```

层级不设上限。项目初创时可能就两层，后面自然长成三层、四层。

---

## 操作流程

### 第一步：开公司

```bash
studio init

#   你要做什么项目？
#   > 前后端分离的Vue3+FastAPI记账应用

#   ⏳ 正在调研...

#   ┌──────────────────────────────────────────────────┐
#   │   推荐公司架构（基于调研）                          │
#   │                                                  │
#   │   技术主管                                        │
#   │   ├── 前端开发 (Vue3 组件、状态管理、API对接)       │
#   │   ├── 后端开发 (FastAPI 接口、数据库、认证)         │
#   │   └── 测试审查 (端到端测试、代码质量)               │
#   │                                                  │
#   │  来源：分析了 Web 全栈团队结构                      │
#   │  存档为模板：web-fullstack-vue-fastapi             │
#   │                                                  │
#   │  [1] 确认  [2] 调整岗位  [3] 修改层级              │
#   > 1
#   └──────────────────────────────────────────────────┘

#   确认后，逐岗位配置：

#   技术主管
#     Agent:  [1] Claude Code  [2] Hermes  [3] Cursor  [4] OpenCode  [5] CodeWhale
#     > 1
#     模型:   [1] deepseek-v4-pro  [2] deepseek-v4-flash  [3] qwen
#     > 1
#     起名:   老王

#   前端开发 → 小红 / Cursor / v4 Flash
#   后端开发 → 大壮 / Claude Code / v4 Pro
#   测试审查 → 小严 / OpenCode / v4 Flash

#   [确认开工]
```

### 第二步：日常下命令

```bash
studio task "给首页加个搜索框，支持模糊搜索和搜索历史"

#   命令到达 → 老王（技术主管）收到
#   老王自己拆成子任务 → 分给小红和大壮
#   小严的测试任务自动阻塞，等小红和大壮都完成才触发
```

### 第三步：看进度

```bash
studio status

#   小红 (前端开发)  ████████░░  80%  正在写搜索框组件
#   大壮 (后端开发)  ██████████  100% 已提交，待审查
#   小严 (测试审查)  ░░░░░░░░░░   0%  阻塞中（等待前端+后端完成）
```

### 第四步：审批

```bash
studio review

#   老王已审查通过，等待你最终确认：
#
#   大壮的提交：新增 /api/search 接口，支持 ?q= 查询和分页
#   [1] 通过  [2] 打回  [3] 看详情
#   > 1
```

---

## 扩建公司

公司不是一次建成不变的。三个维度的扩建：

```bash
studio expand

#   扩建什么？
#   [1] 开新业务线（加部门）  ← "Web做完了，要做小程序"
#   [2] 加管理层（两层变三层） ← "老王管不过来了"
#   [3] 部门内加人          ← "小红一个人写前端太慢"
```

### 场景 A：开新业务线

```bash
studio expand 1 "开发微信小程序"

#   ⏳ 调研小程序开发需要什么岗位...
#
#   推荐新增部门：小程序部
#     小程序主管（向老王汇报）
#       ├── 小程序前端 (uni-app / 原生)
#       └── 云函数后端
#
#   检测到：现有全栈测试工作量翻倍
#   建议：扩招 1 名测试，或拆分为 Web测试 + 小程序测试
#   [1] 采纳建议  [2] 只加部门别的不管
#   > 2
#
#   小程序主管：新岗 / Claude Code / v4 Pro / 你起名
```

### 场景 B：加管理层

```bash
studio expand 2

#   当前组织：
#   老王 ──┬── 小红
#         ├── 大壮
#         ├── 小严
#         ├── 小新 ──┬── 小码
#         │          └── 小云
#         └── 小美（新招的前端）    ← 老王管6个人了
#
#   哪个部门需要加管理层？
#   [1] 老王直辖的前端团队（小红+小美）
#   [2] 小新的小程序部（小码+小云）
#   > 1
#
#   推荐新岗位：前端组长
#   管理：小红、小美
#   向老王汇报
#   [1] 创建前端组长岗位  [2] 提升小红为组长  [3] 取消
```

### 场景 C：部门内加人

```bash
studio expand 3

#   哪个部门？
#   > 前端 (小红)
#
#   要加什么岗位？
#   [1] 再加一个前端开发（同级）
#   [2] 专门做性能优化的
#   [3] 专门做 UI 动效的
#   [4] 自定义
#   > 2
#
#   前端性能优化 → 新岗 / Claude Code / v4 Flash / 小快
#   向小红汇报（因为小红是前端组长）
```

---

## 调研机制

系统接到项目描述后，用 web_search 查：

1. 这类项目通常需要什么开发角色
2. 各角色的职责边界
3. 团队结构的行业惯例

综合结果生成岗位树。调研结果存档为模板，下次类似项目直接复用。

```
第一次："Vue3+FastAPI记账应用" → web_search 调研 → 存档 web-fullstack-vue-fastapi
第二次："Vue3+FastAPI博客"     → 检测到相似模板 → 直接复用（问用户是否要重新调研）
第三次："微信小程序商城"       → 无匹配模板 → 重新调研 → 存档 miniapp-wechat-shop
```

调研提示词（发给搜索引擎的）：

> 做「<项目描述>」这种项目，标准的开发团队需要哪些技术岗位？各岗位的职责和汇报关系是什么？用中文回答。

---

## 上报机制

以下情况主管必须上报 CEO，不能自己做决定：

- 涉及架构决策（换技术栈、改数据模型）
- 安全相关（认证、权限、加密）
- 需要引入新的第三方依赖
- 两个 Worker 的方案有不可调和的冲突
- 任务超出当前岗位能力范围
- 发现需要新建/拆分岗位

以下情况主管可以自己处理，事后汇报即可：

- 代码审查通过/打回
- 任务分配和排期
- 技术实现细节的选择
- 小的性能优化

---

## Agent 隔离：Git Worktree

每个 Worker 独享一个 Git Worktree。Worker A 在 `workspaces/task-001/` 里改代码，Worker B 在 `workspaces/task-002/` 里看的是原始主分支代码，互相不可见。直到主管审查通过并合并。

```
主仓库: /path/to/project/
  ├── .git/
  └── workspaces/                  # git worktree 工作区
        ├── task-001-search-ui/    # Worker A 独享
        ├── task-002-search-api/   # Worker B 独享
        └── task-003-e2e-test/     # Worker C 独享
```

## 任务生命周期

```
pending         → 任务已创建，等待主管拆解
assigned        → 主管拆解完毕，已分配给 Worker
in_progress     → Worker 正在执行
submitted       → Worker 提交，等待主管审查
in_review       → 主管正在审查
  ├── approved  → 审查通过，合并到主分支，通知 CEO
  ├── rejected  → 打回 Worker，附带修改意见
  └── escalated → 上报 CEO 决策
archived        → 已完成，归档
blocked         → 阻塞中（依赖未完成）
```

## 依赖链

```yaml
# 前端完成 → 后端完成 → 端到端测试才能开始
qa:
  waits_on: [frontend, backend]
```

系统自动检测依赖状态：

- 依赖未全部完成 → 任务保持 blocked，不发给 Worker
- 依赖全部完成 → 自动解除 blocked → Worker 收到通知开工

---

## Agent 技能使用：三道防线

加载技能 ≠ 技能被用。Agent 可能在上下文中能看到技能内容，但模型不一定会主动遵守。需要三道防线来逼近 100% 的技能利用率。

这套机制对应真实公司的管理流程：

| 防线 | 公司类比 | 系统做的事 |
|------|---------|-----------|
| 防线一：加载技能 | 入职培训，发了规范手册 | 启动 Worker 时自动加载 `-s skill-name`、连接 MCP |
| 防线二：任务点名 | 主管说"这次用手册第三章的模板" | 主管在任务描述里明确引用具体技能 |
| 防线三：审查纠正 | 质检抽查，不合格打回 | 审查者检查代码是否遵守技能规范，不遵守 → 打回 |

### 防线一：加载技能（系统自动）

启动 Worker 时，系统根据 `resume` 字段自动带上技能和 MCP：

```python
# agents/hermes.py — 系统层，不需要主管操心
def run(agent_config, task, worktree):
    cmd = ["hermes", "chat", "-q", task]
    if agent_config.resume.skills:
        cmd += ["-s", ",".join(agent_config.resume.skills)]  # 自动加载
    if agent_config.resume.mcp_servers:
        for mcp in agent_config.resume.mcp_servers:
            cmd += ["--mcp", mcp]                              # 自动连接
    subprocess.run(cmd, cwd=worktree)
```

### 防线二：任务里点名技能（主管负责）

主管拆任务之前，系统先把团队简历注入主管的上下文。主管拿到简历后，在任务描述里点名具体技能：

```
主管（老王）收到的上下文：

你的团队成员：
- 大壮 / 后端开发（Hermes）
  技能：fastapi-expert, python-async
  MCP：postgres-mcp
  擅长：REST API, 数据库, 认证
- 小红 / 前端开发（Cursor）
  技能：vue-debug
  擅长：Vue3组件, Pinia, Tailwind CSS
- 小严 / 测试审查（OpenCode）
  擅长：代码审查, 端到端测试

拆分任务时，在任务描述里点名各成员应使用的技能。

老王输出的任务：
→ 大壮："写 /api/search 接口。
        用 postgres-mcp 连数据库查询，
        返回格式遵守 fastapi-expert 第3节规范，
        数据库查询用 python-async 的异步模式"
→ 小红："写搜索框组件，调 /api/search。
        用 Pinia 管搜索状态，
        参考 vue-debug 的代码格式规范"
```

### 防线三：审查者检查技能合规（自愈）

审查者（小严）不仅检查功能是否正确，还检查**是否遵守了技能规范**：

```
小严收到的审查任务：

检查大壮写的 /api/search 代码：
1. [功能] 接口能正常返回搜索结果
2. [技能合规] 返回格式遵守 fastapi-expert 规范
3. [技能合规] 数据库查询使用了 python-async 异步模式
4. [MCP 合规] 使用了 postgres-mcp 连接数据库

违规 → 打回，指出具体违规点
合规 → 通过

检查小红写的搜索框组件：
1. [功能] 能正常搜索
2. [技能合规] 代码格式遵守 vue-debug 规范
```

### 完整链路

```
系统（HR）              老王（主管）              小红/大壮（工人）        小严（质检）
  │                       │                          │                    │
  │ 投喂团队简历          │                          │                    │
  ├──────────────────────→│                          │                    │
  │                       │                          │                    │
  │                   看简历：                        │                    │
  │                   "大壮有fastapi-expert           │                    │
  │                    和 postgres-mcp，              │                    │
  │                    接口交给他放心"                 │                    │
  │                       │                          │                    │
  │                   写任务（含技能引用）               │                    │
  │                       │                          │                    │
  │            ┌──────────┴──────────┐               │                    │
  │            │                     │               │                    │
  │   给大壮：               给小红：                  │                    │
  │   "用postgres-mcp...    "参考vue-debug..."        │                    │
  │            │                     │               │                    │
  │            ▼                     ▼               │                    │
  │   系统启动：              系统启动：                │                    │
  │   -s fastapi-expert,     worktree隔离             │                    │
  │   python-async                                   │                    │
  │   + MCP postgres                                 │                    │
  │            │                     │               │                    │
  │            ▼                     ▼               │                    │
  │      大壮写代码             小红写代码              │                    │
  │    (防线一：技能已加载)    (防线一：技能已加载)       │                    │
  │    (防线二：任务已点名)    (防线二：任务已点名)       │                    │
  │            │                     │               │                    │
  │            └──────────┬──────────┘               │                    │
  │                       │                          │                    │
  │                   双方提交                         │                    │
  │                       │                          │                    │
  │                       └─────────────────────────→│                    │
  │                                                  │                    │
  │                                          防线三：检查技能合规           │
  │                                            ├── 遵守 → 通过            │
  │                                            └── 违规 → 打回 ← 自愈     │
  │                                                  │                    │
  │                                           汇报 CEO                   │
  │                       ←──────────────────────────┘                    │
```

三道防线加起来才能逼近 100%。单靠哪一层都不够，就像现实公司没有哪个制度能保证员工 100% 遵守规范，靠的是审查 + 修正的循环。

---

## 配置体系

### agents.yaml（系统级，你在工具中注册了哪些 Agent）

```yaml
agents:
  claude-code:
    name: Claude Code
    command: claude
    flags: "-p"
    strengths: [复杂推理, 自主迭代, 代码审查]
    works_with: [deepseek-v4-pro, deepseek-v4-flash, qwen, claude-sonnet]

  cursor:
    name: Cursor
    command: cursor
    flags: "--task"
    strengths: [前端UI, IDE诊断, 组件生成]
    works_with: [deepseek-v4-pro, deepseek-v4-flash]

  hermes:
    name: Hermes
    command: hermes
    flags: "chat -q"
    strengths: [持久记忆, 文档, 配置, 脚本]
    works_with: [deepseek-v4-pro, deepseek-v4-flash, qwen]

  opencode:
    name: OpenCode
    command: opencode
    flags: ""
    strengths: [代码审查, 重构, 格式化]
    works_with: [deepseek-v4-pro, deepseek-v4-flash]

  codewhale:
    name: CodeWhale
    command: codewhale
    flags: ""
    strengths: [轻量脚本, 工具函数]
    works_with: [deepseek-v4-flash]
```

### models.yaml（系统级）

```yaml
models:
  deepseek-v4-pro:
    name: DeepSeek v4 Pro
    cost: high
    use_when: [技术主管, 代码审查, 复杂逻辑]

  deepseek-v4-flash:
    name: DeepSeek v4 Flash
    cost: low
    use_when: [简单CRUD, 文档, 脚本, UI组件]

  qwen:
    name: Qwen
    cost: low
    use_when: [文档, 配置, 轻量任务]
```

### 项目级 positions.yaml

```yaml
project: todo-accounting
description: Vue3+FastAPI 记账应用
created: 2026-06-07

positions:
  - id: laowang
    name: 老王
    title: 技术主管
    parent: null
    agent: claude-code
    model: deepseek-v4-pro
    is_manager: true
    resume:                                              # ← 简历：主管不需要具体技能，但要知道团队全貌
      strengths: [任务拆解, 技术决策, 代码审查]

  - id: xiaohong
    name: 小红
    title: 前端开发
    parent: laowang
    agent: cursor
    model: deepseek-v4-flash
    resume:
      strengths: [Vue3组件, Pinia状态管理, Tailwind CSS]
      skills: [vue-debug]

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

  - id: xiaoyan
    name: 小严
    title: 测试审查
    parent: laowang
    agent: opencode
    model: deepseek-v4-flash
    waits_on: [xiaohong, dazhuang]
    resume:
      strengths: [代码审查, 端到端测试, 接口测试]
      skills: []
```

### 项目模板（调研结果存档）

```yaml
# templates/web-fullstack-vue-fastapi.yaml
name: Web 全栈 (Vue3 + FastAPI)
source: web_research
searched_at: 2026-06-07
keywords: [前后端分离, web, vue, fastapi, 全栈]

positions:
  - id: tech-lead
    title: 技术主管
    parent: null
    manages: [frontend, backend, qa]
    does: 拆解任务、技术决策、代码审查
    recommend: { agent: claude-code, model: deepseek-v4-pro }

  - id: frontend
    title: 前端开发
    parent: tech-lead
    waits_on: []
    does: Vue3组件、状态管理、API对接、样式
    recommend: { agent: cursor, model: deepseek-v4-flash }

  - id: backend
    title: 后端开发
    parent: tech-lead
    waits_on: []
    does: FastAPI接口、数据库模型、认证
    recommend: { agent: claude-code, model: deepseek-v4-pro }

  - id: qa
    title: 测试审查
    parent: tech-lead
    waits_on: [frontend, backend]
    does: 端到端测试、接口测试、代码质量检查
    recommend: { agent: opencode, model: deepseek-v4-flash }
```

---

## 项目结构

```
IntAgentCollaborationDevelopStudio/
├── cli/studio.py               # CLI 主入口 (studio 命令)
├── config/
│   ├── agents.yaml             # 系统级：可用 Agent 注册表
│   ├── models.yaml             # 系统级：可用模型注册表
│   ├── platform.yaml           # 中台与 Supervisor 配置
│   └── templates/              # 调研存档的项目模板 (Phase 3)
├── core/
│   ├── project.py              # studio init / 项目路径
│   ├── org/
│   │   ├── tree_ops.py         # 组织树 CRUD
│   │   └── org_chart.py        # 渲染组织架构树
│   ├── dispatch/
│   │   ├── dispatcher.py       # 收任务 → 发给主管
│   │   └── task_fsm.py         # 任务状态机
│   ├── ipc/message_bus.py      # Agent inbox 消息
│   ├── workspace/worktree.py   # Git Worktree 创建/清理
│   ├── supervisor/registry.py  # 端口/进程注册 (Python 回退)
│   └── supervisor_client.py    # Supervisor 客户端
├── supervisor/                 # Go 调度守护进程 (需 Go 1.22+)
│   ├── cmd/studio-supervisor/
│   ├── pkg/lock/               # 端口租约
│   └── pkg/process/            # 进程注册
├── agents/                     # Agent 适配层
│   ├── base.py
│   ├── claude_code.py
│   └── registry.py
├── platform/                   # 全局中台 (Phase 2)
│   ├── memory/
│   ├── skills/
│   └── mcp/
└── projects/                   # 你创建的项目（不可提交到 Git）
    └── {project-id}/
        ├── positions.yaml
        ├── agents/{id}/inbox/  # 消息收件箱
        ├── tasks/active/
        └── workspaces/         # Git Worktree 工作区
```

### CLI 用法 (Phase 1)

```bash
pip install -e ".[dev]"
studio init --name demo --repo .
studio task "给首页加个搜索框"
studio status
studio review
```

---

## 技术选型

- **语言**：Python 3.11+（业务层）+ Go 1.22+（Supervisor，可选）
- **界面**：纯 CLI（argparse），零 UI 依赖
- **隔离**：Git Worktree + Agent 私有沙箱目录
- **配置**：YAML
- **Agent 调用**：subprocess（CLI 命令行调用）
- **调度**：Go Supervisor gRPC（或 Python 注册表回退）
- **存储**：YAML + 文件 inbox，无数据库

## 开发原则

- 先跑通最小闭环：studio init + studio task + studio status + studio review
- 再加扩建（expand）
- 最后加调研（research）和模板复用
- 每一个功能做完都用真实 Agent 跑一次验证
- 不做 Web UI、不做数据库、不做通用插件化
