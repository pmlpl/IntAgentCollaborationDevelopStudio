# Phase 2 — Skills / MCP / 记忆 / RBAC

**Goal:** 全局中台 + 层级 RBAC + 三道防线资源注入

**已完成：**

### 第一步 — Skills 中台
- `platform/skills/registry.yaml` + 3 个示例技能包
- `core/platform/skills_client.py` — 解析 resume.skills、写 `skills.manifest.yaml`
- `agents/runner.py` — spawn 前注入 `-s skill1,skill2`
- 主管拆解 prompt 含 skills 摘要
- `studio skills list`
- 默认岗位 resume 含 skills（大壮、小红）

### 第二步 — MCP + RBAC + 记忆 + 防线三
- `platform/mcp/registry.yaml` + `gateway/config.yaml` 骨架
- `core/platform/mcp_client.py` — 注册表、RBAC、`McpGateway` stub、审计日志
- `core/rbac/` — `permission.py` + `inherit.py`（visible / use / edit）
- Skills/MCP 解析接入 RBAC（`prepare_worker_runtime` 写 manifest + allowlist）
- `core/platform/memory_client.py` — 文件后端 search/upsert/delete + RBAC
- `config/platform.yaml` — 中台全局配置
- `core/dispatch/review_compliance.py` — 防线三审查清单
- CLI：`studio mcp list`、`studio memory list|search|upsert`
- TUI 审批屏展示技能合规清单
- 大壮默认 `mcp_servers: [postgres-mcp]`

**下一步（Phase 3）：** → 见 [2026-06-07-phase3-expand-org.md](./2026-06-07-phase3-expand-org.md)（已完成 org/expand CLI）

**后续增强：**
- MCP Gateway 真实 stdio 连接池
- ChromaDB 向量检索（可选依赖）
- web_search 真实调研
