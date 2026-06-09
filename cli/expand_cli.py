# cli/expand_cli.py — studio expand 子命令
from __future__ import annotations

import sys

from core.org.expand_ops import (
    expand_add_role,
    expand_business_line,
    expand_insert_manager,
    list_missing_roles,
)
from core.org.org_chart import render_tree
from core.org.persist import load_positions_data
from core.org.tree_ops import OrgTree, OrgTreeError
from core.project import get_role_catalog, get_studio_root, load_project
from core.research.expand import mock_expand_research


def _project_dir(root, project: str | None):
    return load_project(root, project)


def cmd_expand_business(args) -> int:
    root = get_studio_root()
    project_dir = _project_dir(root, args.project)
    description = args.description or "新业务线"
    research = mock_expand_research(description, project_dir=project_dir)
    print(research["summary"])
    tpl = args.template or str(research["recommended_template"])
    data = load_positions_data(project_dir)
    missing = list_missing_roles(data, tpl)
    if not missing and not args.yes:
        suggested = research.get("suggested_roles") or []
        missing = [r for r in suggested if r not in {p["id"] for p in data["positions"]}]
    if not missing:
        print("无需新增岗位。", file=sys.stderr)
        return 1
    print(f"\n将新增岗位: {', '.join(missing)}")
    if not args.yes:
        print("若确认，请加上 --yes")
        return 1
    try:
        _, added = expand_business_line(
            project_dir,
            description,
            template_id=tpl,
            role_ids=missing,
        )
    except (OrgTreeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"✓ 扩建完成，新增: {', '.join(added)}")
    data = load_positions_data(project_dir)
    print(render_tree(data.get("positions", [])))
    return 0


def cmd_expand_role(args) -> int:
    root = get_studio_root()
    project_dir = _project_dir(root, args.project)
    try:
        expand_add_role(project_dir, args.role, parent_id=args.parent)
    except (OrgTreeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"✓ 已添加岗位: {args.role}")
    data = load_positions_data(project_dir)
    print(render_tree(data.get("positions", [])))
    return 0


def cmd_expand_manager(args) -> int:
    root = get_studio_root()
    project_dir = _project_dir(root, args.project)
    child_ids = [x.strip() for x in args.children.split(",") if x.strip()]
    spec = {
        "id": args.id,
        "name": args.name or args.id,
        "title": args.title or "组长",
        "parent": args.reports_to,
        "agent": args.agent or "opencode",
        "model": args.model or "deepseek-v4-pro",
        "is_manager": True,
        "resume": {"strengths": ["团队协调", "任务分配"]},
    }
    try:
        expand_insert_manager(project_dir, spec, child_ids)
    except OrgTreeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"✓ 已创建管理层: {args.name} ({args.id})")
    data = load_positions_data(project_dir)
    print(render_tree(data.get("positions", [])))
    return 0


def cmd_expand_interactive(args) -> int:
    """无子命令时进入交互式扩建向导。"""
    import questionary

    root = get_studio_root()
    project_dir = _project_dir(root, args.project)
    data = load_positions_data(project_dir)
    tree = OrgTree.from_yaml_data(data)
    positions = data.get("positions", [])

    mode = questionary.select(
        "扩建什么？",
        choices=[
            questionary.Choice("开新业务线（加部门/岗位）", value="business"),
            questionary.Choice("加管理层（插入主管）", value="manager"),
            questionary.Choice("部门内加人", value="role"),
        ],
    ).ask()
    if not mode:
        return 1

    if mode == "business":
        desc = questionary.text("新业务描述（如：开发微信小程序）").ask()
        if not desc:
            return 1
        research = mock_expand_research(desc)
        print("\n" + str(research["summary"]))
        tpl = str(research["recommended_template"])
        missing = list_missing_roles(data, tpl)
        if not missing:
            missing = [
                r
                for r in (research.get("suggested_roles") or [])
                if r not in {p["id"] for p in positions}
            ]
        if not missing:
            print("没有可新增岗位。")
            return 1
        ok = questionary.confirm(f"新增岗位: {', '.join(missing)} ?", default=True).ask()
        if not ok:
            return 1
        try:
            expand_business_line(project_dir, desc, template_id=tpl, role_ids=missing)
        except (OrgTreeError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print("✓ 扩建完成")

    elif mode == "role":
        catalog = get_role_catalog()
        existing = {p["id"] for p in positions}
        choices = [
            questionary.Choice(f"{meta.get('name')} · {meta.get('title')} ({rid})", value=rid)
            for rid, meta in catalog.items()
            if rid not in existing
        ]
        if not choices:
            print("岗位目录中无可添加角色。")
            return 1
        role_id = questionary.select("选择要添加的岗位", choices=choices).ask()
        if not role_id:
            return 1
        parent_choices = [
            questionary.Choice(f"{p.get('name')} ({p['id']})", value=p["id"]) for p in positions
        ]
        parent_id = questionary.select("向谁汇报？", choices=parent_choices).ask()
        try:
            expand_add_role(project_dir, role_id, parent_id=parent_id)
        except (OrgTreeError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"✓ 已添加: {role_id}")

    elif mode == "manager":
        child_choices = [
            questionary.Choice(f"{p.get('name')} ({p['id']})", value=p["id"])
            for p in positions
            if not p.get("is_manager")
        ]
        children = questionary.checkbox("选择改由新主管管理的下属", choices=child_choices).ask()
        if not children:
            return 1
        new_id = questionary.text("新主管 id（英文）", default="team-lead").ask()
        new_name = questionary.text("花名", default="新主管").ask()
        reports = questionary.select(
            "新主管向谁汇报？",
            choices=[
                questionary.Choice(f"{p.get('name')} ({p['id']})", value=p["id"])
                for p in positions
                if p.get("is_manager") or p.get("parent") is None
            ],
        ).ask()
        spec = {
            "id": new_id,
            "name": new_name,
            "title": "组长",
            "parent": reports,
            "agent": "opencode",
            "model": "deepseek-v4-pro",
            "is_manager": True,
            "resume": {"strengths": ["团队协调"]},
        }
        try:
            expand_insert_manager(project_dir, spec, children)
        except OrgTreeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"✓ 已创建管理层: {new_name}")

    data = load_positions_data(project_dir)
    print("\n" + render_tree(data.get("positions", [])))
    return 0
