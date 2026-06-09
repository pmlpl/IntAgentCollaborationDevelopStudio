# cli/org_cli.py — studio org 子命令
from __future__ import annotations

import sys

from core.org.org_chart import render_tree
from core.org.persist import load_positions_data, save_positions_data
from core.org.tree_ops import OrgTree, OrgTreeError
from core.project import get_studio_root, load_project, resolve_project_id


def _project_dir(root, project: str | None):
    return load_project(root, project)


def cmd_org_show(args) -> int:
    root = get_studio_root()
    project_dir = _project_dir(root, args.project)
    data = load_positions_data(project_dir)
    print(f"项目: {data.get('project', resolve_project_id(root, args.project))}")
    print(render_tree(data.get("positions", [])))
    return 0


def cmd_org_add(args) -> int:
    root = get_studio_root()
    project_dir = _project_dir(root, args.project)
    from core.org.expand_ops import expand_add_role

    try:
        expand_add_role(project_dir, args.role, parent_id=args.parent)
    except (OrgTreeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"✓ 已添加岗位: {args.role} → 上级 {args.parent or '(catalog 默认)'}")
    return 0


def cmd_org_move(args) -> int:
    root = get_studio_root()
    project_dir = _project_dir(root, args.project)
    data = load_positions_data(project_dir)
    tree = OrgTree.from_yaml_data(data)
    try:
        tree.move_subtree(args.node, args.parent)
    except OrgTreeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    meta = {k: v for k, v in data.items() if k != "positions"}
    save_positions_data(
        project_dir,
        {**meta, "positions": tree.to_list()},
        reason=f"move {args.node} → {args.parent}",
    )
    print(f"✓ 已移动: {args.node} → {args.parent}")
    return 0


def cmd_org_remove(args) -> int:
    root = get_studio_root()
    project_dir = _project_dir(root, args.project)
    data = load_positions_data(project_dir)
    tree = OrgTree.from_yaml_data(data)
    try:
        tree.remove_node(args.node, strategy=args.strategy)
    except OrgTreeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    meta = {k: v for k, v in data.items() if k != "positions"}
    save_positions_data(
        project_dir,
        {**meta, "positions": tree.to_list()},
        reason=f"remove {args.node} ({args.strategy})",
    )
    print(f"✓ 已删除岗位: {args.node}")
    return 0
