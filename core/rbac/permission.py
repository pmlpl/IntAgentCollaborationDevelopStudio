# core/rbac/permission.py — 有效权限计算
from __future__ import annotations

from typing import Any, Literal

from core.org.tree_ops import OrgTree
from core.rbac.inherit import collect_domain_grants, collect_resume_ids, get_position

MemoryAction = Literal["read", "read_write", "write", "none"]


def effective_skill_use(
    tree: OrgTree,
    position: dict[str, Any],
    registry_ids: set[str],
) -> set[str]:
    """岗位可「使用」的技能 id（resume + 继承；主管额外继承直属下属技能）。"""
    pid = position.get("id", "")
    allowed = collect_resume_ids(position, "skills")
    allowed |= collect_domain_grants(tree, pid, "skills", "use")
    if position.get("is_manager"):
        # 主管可继承直属下属声明的技能（而非全注册表），便于审核与代理工作
        allowed |= _collect_direct_reports_resume(tree, pid, "skills")
    return allowed & registry_ids


def effective_visible_skills(
    tree: OrgTree,
    position: dict[str, Any],
    registry_ids: set[str],
) -> set[str]:
    """resume / 上级 visible + use 并集，用于主管拆解时展示团队能力。

    主管可查看所有注册技能（用于任务分配），但使用仅限 effective_skill_use 范围。
    """
    pid = position.get("id", "")
    allowed = effective_skill_use(tree, position, registry_ids)
    allowed |= collect_domain_grants(tree, pid, "skills", "visible")
    if position.get("is_manager"):
        # 主管可以「看到」所有注册技能以便调配，但实际使用由 effective_skill_use 控制
        allowed |= registry_ids
    return allowed & registry_ids


def effective_mcp_use(
    tree: OrgTree,
    position: dict[str, Any],
    registry_ids: set[str],
) -> set[str]:
    """岗位可使用的 MCP server id（resume + 继承；主管额外继承直属下属 MCP）。"""
    pid = position.get("id", "")
    allowed = collect_resume_ids(position, "mcp")
    allowed |= collect_domain_grants(tree, pid, "mcp", "use")
    if position.get("is_manager"):
        # 主管可继承直属下属声明的 MCP（而非全注册表）
        allowed |= _collect_direct_reports_resume(tree, pid, "mcp")
    return allowed & registry_ids


def _collect_direct_reports_resume(
    tree: OrgTree, manager_id: str, domain: str
) -> set[str]:
    """收集直属下属的 resume 声明的 skills / mcp_servers。"""
    ids: set[str] = set()
    for child_id in tree.children(manager_id):
        child = tree.get(child_id)
        if child:
            ids |= collect_resume_ids(child, domain)
    return ids


def memory_access(
    tree: OrgTree,
    position: dict[str, Any],
    namespace: str,
    *,
    project_id: str | None = None,
) -> MemoryAction:
    """判断岗位对某记忆命名空间的读写权限。"""
    pid = position.get("id", "")
    block = (position.get("permissions") or {}).get("memory") or {}

    if namespace == "global":
        level = block.get("global", "read")
        if level in ("read_write", "write"):
            return "read_write"
        return "read"

    if namespace.startswith("project/"):
        ns_project = namespace.split("/", 1)[1]
        if project_id and ns_project != project_id:
            return "none"
        level = block.get("project", "read")
        if level in ("read_write", "write"):
            return "read_write"
        # 主管对项目记忆有读写权（需要记录拆解/审查决策）
        if position.get("is_manager"):
            return "read_write"
        return "read"

    if namespace.startswith("agent/"):
        owner = namespace.split("/", 1)[1]
        if owner == pid:
            return "read_write"
        if owner in tree.subtree(pid) and position.get("is_manager"):
            return "read"
        for anc in tree.ancestors(owner):
            if anc == pid and position.get("is_manager"):
                return "read"
        return "none"

    return "none"
