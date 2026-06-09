# Phase 3 — 扩建与组织编辑

**Goal:** 公司可动态扩建；组织树可 CLI 编辑；调研 mock 可扩展为 web_search

**已完成：**

- `core/org/persist.py` — positions 读写 + `org.snapshot.yaml` 审计
- `core/org/tree_ops.py` — `remove_node` / `children` / `get`
- `core/research/expand.py` — 扩建 mock 调研
- `core/org/expand_ops.py` — 新业务线 / 加人 / 插入管理层
- `cli/org_cli.py` — `studio org show|add|move|remove`
- `cli/expand_cli.py` — `studio expand` 交互向导 + 子命令

- TUI 扩建入口（指挥舱 **E** / 「扩建公司」按钮）→ `cli/tui/screens/expand.py`

**CLI 示例：**

```bash
studio org show
studio org add xiaomo --parent laowang
studio org move xiaohong --parent team-lead
studio org remove xiaomo --strategy archive

studio expand                              # 交互式
studio expand business "微信小程序" --yes
studio expand role xiaomo --parent laowang
studio expand manager --id frontend-lead --name 前端组长 --reports-to laowang --children xiaohong
```

**下一步（Phase 4a — 项目画像）：**

- `core/project_profile.py` — 每项目 `PROJECT.md` 读写与合并
- 调研 Agent 先读画像 → 再联网 → 写回画像
- 开公司 / 扩建确认后持久化 PROJECT.md

**后续（Phase 4b+）：**

- 任务执行后 merge 实际技术栈到 PROJECT.md
- MCP Gateway stdio 连接池
- ChromaDB 向量记忆（optional）
