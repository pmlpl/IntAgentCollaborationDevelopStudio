# core/rbac/inherit.py — 上级授权向下继承
from __future__ import annotations

from typing import Any

from core.org.tree_ops import OrgTree


def get_position(tree: OrgTree, position_id: str) -> dict[str, Any] | None:
    """按 id 查找岗位。"""
    for pos in tree.to_list():
        if pos.get("id") == position_id:
            return pos
    return None


def collect_domain_grants(
    tree: OrgTree,
    position_id: str,
    domain: str,
    action: str,
) -> set[str]:
    """合并岗位自身 + 全部上级的显式授权（use / edit / visible）。"""
    grants: set[str] = set()
    cur: str | None = position_id
    seen: set[str] = set()
    while cur is not None and cur not in seen:
        seen.add(cur)
        pos = get_position(tree, cur)
        if not pos:
            break
        block = (pos.get("permissions") or {}).get(domain) or {}
        for item in block.get(action) or []:
            grants.add(str(item))
        cur = pos.get("parent")
    return grants


def collect_resume_ids(position: dict[str, Any], domain: str) -> set[str]:
    """从 resume 读取岗位声明的 skills / mcp_servers。"""
    resume = position.get("resume") or {}
    if domain == "skills":
        return {str(x) for x in (resume.get("skills") or [])}
    if domain == "mcp":
        return {str(x) for x in (resume.get("mcp_servers") or [])}
    return set()
