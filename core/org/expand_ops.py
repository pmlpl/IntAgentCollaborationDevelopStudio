# core/org/expand_ops.py — 公司扩建：新业务线 / 加管理层 / 加人
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from core.org.persist import (
    apply_tree,
    ensure_agent_sandbox,
    load_positions_data,
)
from core.org.tree_ops import OrgTree, OrgTreeError
from core.project import ORG_TEMPLATES, get_role_catalog
from core.research.expand import mock_expand_research


def _meta_without_positions(data: dict[str, Any]) -> dict[str, Any]:
    meta = deepcopy(data)
    meta.pop("positions", None)
    return meta


def list_missing_roles(data: dict[str, Any], template_id: str) -> list[str]:
    """对比模板，返回当前组织缺少的岗位 id。"""
    if template_id not in ORG_TEMPLATES:
        raise ValueError(f"unknown template: {template_id}")
    current = {p["id"] for p in data.get("positions", [])}
    return [rid for rid in ORG_TEMPLATES[template_id]["roles"] if rid not in current]


def expand_business_line(
    project_dir: Path,
    description: str,
    *,
    template_id: str | None = None,
    role_ids: list[str] | None = None,
) -> tuple[OrgTree, list[str]]:
    """开新业务线：调研后追加模板中缺失岗位。"""
    data = load_positions_data(project_dir)
    research = mock_expand_research(description)
    tpl = template_id or str(research["recommended_template"])
    to_add = role_ids if role_ids is not None else list_missing_roles(data, tpl)
    if not to_add:
        suggested = research.get("suggested_roles") or []
        existing = {p["id"] for p in data["positions"]}
        to_add = [r for r in suggested if r not in existing]
    if not to_add:
        raise ValueError("没有可新增岗位（当前组织已包含推荐编制）")

    catalog = get_role_catalog()
    tree = OrgTree.from_yaml_data(data)
    added: list[str] = []
    current_ids = {p["id"] for p in tree.to_list()}
    for rid in to_add:
        if rid in current_ids:
            continue
        if rid not in catalog:
            raise ValueError(f"unknown role: {rid}")
        spec = deepcopy(catalog[rid])
        parent = spec.get("parent")
        if parent and parent not in current_ids:
            managers = tree.root_managers()
            parent = managers[0] if managers else parent
            spec["parent"] = parent
        tree.add_node(spec["parent"], spec)
        ensure_agent_sandbox(project_dir, rid)
        added.append(rid)
        current_ids.add(rid)

    apply_tree(
        project_dir,
        tree,
        _meta_without_positions(data),
        reason=f"expand business: {description[:60]}",
    )
    return tree, added


def expand_add_role(
    project_dir: Path,
    role_id: str,
    *,
    parent_id: str | None = None,
) -> OrgTree:
    """部门内加人：从岗位目录追加一个角色。"""
    data = load_positions_data(project_dir)
    catalog = get_role_catalog()
    if role_id not in catalog:
        raise ValueError(f"unknown role: {role_id}")

    tree = OrgTree.from_yaml_data(data)
    if role_id in {p["id"] for p in tree.to_list()}:
        raise OrgTreeError(f"role already exists: {role_id}")

    spec = deepcopy(catalog[role_id])
    parent = parent_id or spec.get("parent")
    if not parent:
        managers = tree.root_managers()
        parent = managers[0] if managers else None
    if not parent or parent not in {p["id"] for p in tree.to_list()}:
        raise OrgTreeError(f"invalid parent: {parent!r}")

    spec["parent"] = parent
    tree.add_node(parent, spec)
    ensure_agent_sandbox(project_dir, role_id)
    apply_tree(project_dir, tree, _meta_without_positions(data), reason=f"expand add role: {role_id}")
    return tree


def expand_insert_manager(
    project_dir: Path,
    manager_spec: dict[str, Any],
    child_ids: list[str],
) -> OrgTree:
    """加管理层：新建主管并将指定下属改向其汇报。"""
    data = load_positions_data(project_dir)
    tree = OrgTree.from_yaml_data(data)
    mid = manager_spec["id"]
    if mid in {p["id"] for p in tree.to_list()}:
        raise OrgTreeError(f"duplicate manager id: {mid}")

    parent_id = manager_spec.get("parent")
    if not parent_id:
        managers = tree.root_managers()
        parent_id = managers[0] if managers else None
    if not parent_id:
        raise OrgTreeError("cannot determine parent for new manager")

    spec = deepcopy(manager_spec)
    spec["parent"] = parent_id
    spec["is_manager"] = True
    tree.add_node(parent_id, spec)
    ensure_agent_sandbox(project_dir, mid)

    for cid in child_ids:
        try:
            tree.get(cid)
        except OrgTreeError as exc:
            raise OrgTreeError(f"unknown child: {cid}") from exc
        tree.move_subtree(cid, mid)

    apply_tree(
        project_dir,
        tree,
        _meta_without_positions(data),
        reason=f"expand manager: {mid}",
    )
    return tree
