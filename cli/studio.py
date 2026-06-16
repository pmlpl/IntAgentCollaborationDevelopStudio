# cli/studio.py — Studio CLI 主入口
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cli.agent_cli import register_agent_commands
from cli.expand_cli import (
    cmd_expand_business,
    cmd_expand_interactive,
    cmd_expand_manager,
    cmd_expand_role,
)
from cli.org_cli import cmd_org_add, cmd_org_move, cmd_org_remove, cmd_org_show
from core.dispatch.dispatcher import get_dispatcher
from core.platform.mcp_client import list_mcp_servers
from core.platform.memory_client import (
    MemoryError,
    list_namespaces,
    resolve_memory_namespace,
    search,
    upsert,
)
from core.platform.skills_client import list_skills
from core.project import (
    delete_project,
    get_registry_entry,
    get_studio_root,
    init_project,
    list_registered_projects,
    load_project,
    resolve_project_id,
    set_current_project,
    update_project,
)
from core.supervisor_client import SupervisorClient


def cmd_init(args: argparse.Namespace) -> int:
    root = get_studio_root()
    SupervisorClient(root).ensure_running()
    project_path = None
    if getattr(args, "path", None):
        project_path = Path(args.path)
    elif args.repo:
        project_path = Path(args.repo)
    project_dir = init_project(
        root,
        args.name,
        project_path=project_path,
        description=getattr(args, "description", None),
    )
    set_current_project(root, args.name)
    entry = get_registry_entry(root, args.name)
    project_root = entry["path"] if entry else str(project_dir.parent)
    print(f"[OK] 项目已创建: {args.name}")
    print(f"  项目文件夹: {project_root}")
    print(f"  数据目录: {project_dir}")
    print(f"  组织: {project_dir / 'positions.yaml'}")
    return 0


def cmd_task(args: argparse.Namespace) -> int:
    root = get_studio_root()
    SupervisorClient(root).ensure_running()
    disp = get_dispatcher(root, args.project)
    if getattr(args, "orchestrate", False):
        task = disp.begin_orchestration(
            root, args.description, spawn_terminals=not args.no_spawn, mock=args.mock
        )
        # CLI 模式轮询：等待主管拆解完成（mock 瞬间完成，真实 Agent 最长等 120s）
        import time

        max_wait = 5 if args.mock else 120
        interval = 0.5 if args.mock else 4
        waited = 0.0
        while waited < max_wait:
            if disp.try_complete_orchestration(
                root, task["id"], spawn_terminals=not args.no_spawn
            ):
                print(f"  编排完成 — {disp.get_status()[0]['status'] if disp.get_status() else 'done'}")
                break
            time.sleep(interval)
            waited += interval
        else:
            print(f"  [!!] 编排未在 {max_wait}s 内完成，请用 studio TUI 或重试")
    else:
        task = disp.create_task(args.description)
    print(f"[OK] 任务已创建: {task['id']}")
    if task.get("status"):
        print(f"  状态: {task['status']}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    root = get_studio_root()
    disp = get_dispatcher(root, args.project)
    tasks = disp.get_status()
    if not tasks:
        print("暂无进行中的任务。")
        return 0
    for task in tasks:
        if task.get("parent_id"):
            continue
        bar = "█" * 5 + "░" * 5
        print(f"  {task['id']}  {bar}  {task['status']}  {task['description'][:40]}")
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    root = get_studio_root()
    disp = get_dispatcher(root, args.project)
    pending = disp.get_pending_reviews()
    if not pending:
        print("暂无待审批项。")
        return 0
    for i, task in enumerate(pending, 1):
        print(f"  [{i}] {task['id']} — {task['description'][:60]} ({task['status']})")
    if args.verdict and args.task_id:
        result = disp.submit_review(args.task_id, args.verdict)
        print(f"[OK] 任务 {args.task_id} → {result['status']}")
    return 0


def cmd_project_list(args: argparse.Namespace) -> int:
    root = get_studio_root()
    items = list_registered_projects(root)
    if not items:
        print("暂无项目。")
        return 0
    for p in items:
        print(f"  {p['id']}")
        print(f"    名称: {p.get('name', '')}")
        print(f"    定位: {p.get('purpose', '')}")
        print(f"    路径: {p.get('path', '')}")
    return 0


def cmd_project_show(args: argparse.Namespace) -> int:
    root = get_studio_root()
    entry = get_registry_entry(root, args.name)
    if not entry:
        print(f"项目不存在: {args.name}", file=sys.stderr)
        return 1
    data_dir = load_project(root, args.name)
    print(yaml_dump_safe(entry, data_dir))
    return 0


def yaml_dump_safe(entry: dict, data_dir: Path) -> str:
    import yaml

    lines = [
        f"id: {entry['id']}",
        f"name: {entry.get('name', '')}",
        f"purpose: {entry.get('purpose', '')}",
        f"path: {entry.get('path', '')}",
        f"data_dir: {data_dir}",
    ]
    pos = data_dir / "positions.yaml"
    if pos.exists():
        meta = yaml.safe_load(pos.read_text(encoding="utf-8")) or {}
        lines.append(f"org_template: {meta.get('org_template', '—')}")
        lines.append(f"positions: {len(meta.get('positions', []))} 个岗位")
    return "\n".join(lines)


def cmd_project_update(args: argparse.Namespace) -> int:
    root = get_studio_root()
    try:
        update_project(
            root,
            args.name,
            name=args.display_name,
            purpose=args.purpose,
            path=Path(args.path) if args.path else None,
        )
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"[OK] 项目已更新: {args.name}")
    return 0


def cmd_project_delete(args: argparse.Namespace) -> int:
    root = get_studio_root()
    if not getattr(args, "yes", False):
        entry = get_registry_entry(root, args.name)
        path = entry.get("path") if entry else "?"
        print(f"将删除整个项目文件夹: {path}")
        print("若确认，请加上 --yes")
        return 1
    try:
        folder_deleted, warning = delete_project(root, args.name, remove_folder=True)
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if warning:
        print(f"[!!] {warning}")
    if folder_deleted:
        print(f"OK 项目已删除（含文件夹）: {args.name}")
    else:
        print(f"OK 项目已从列表移除（文件夹未删除或不存在）: {args.name}")
    return 0


def cmd_skills_list(args: argparse.Namespace) -> int:
    root = get_studio_root()
    items = list_skills(root)
    if not items:
        print("暂无已注册技能。见 platform/skills/registry.yaml")
        return 0
    for s in items:
        print(f"  {s['id']}")
        print(f"    {s.get('name', '')} — {s.get('description', '')}")
        print(f"    package: {s.get('package', '')}")
    return 0


def cmd_mcp_list(args: argparse.Namespace) -> int:
    root = get_studio_root()
    items = list_mcp_servers(root)
    if not items:
        print("暂无已注册 MCP。见 platform/mcp/registry.yaml")
        return 0
    for s in items:
        print(f"  {s['id']}")
        print(f"    {s.get('name', '')} — {s.get('description', '')}")
        print(f"    transport: {s.get('transport', 'stdio')}")
    return 0


def _load_memory_context(root: Path, args: argparse.Namespace) -> tuple[Path, dict, dict]:
    """加载当前项目目录、positions 元数据与岗位。"""
    import yaml

    project_dir = load_project(root, getattr(args, "project", None))
    data = yaml.safe_load((project_dir / "positions.yaml").read_text(encoding="utf-8"))
    position = next(
        (p for p in data.get("positions", []) if p.get("id") == args.position),
        None,
    )
    if not position:
        raise ValueError(f"岗位不存在: {args.position}")
    return project_dir, data, position


def cmd_memory_list(args: argparse.Namespace) -> int:
    root = get_studio_root()
    namespaces = list_namespaces(root)
    if not namespaces:
        print("暂无记忆条目。")
        return 0
    for ns in namespaces:
        print(f"  {ns}")
    return 0


def cmd_memory_search(args: argparse.Namespace) -> int:
    root = get_studio_root()
    try:
        project_dir, data, position = _load_memory_context(root, args)
        pid = data.get("project") or resolve_project_id(root, getattr(args, "project", None))
        namespace = resolve_memory_namespace(args.namespace, pid)
    except (FileNotFoundError, ValueError, MemoryError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    try:
        hits = search(
            root,
            project_dir,
            position,
            namespace,
            args.query,
            project_id=pid,
            limit=args.limit,
        )
    except MemoryError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not hits:
        print("无匹配结果。")
        return 0
    for item in hits:
        print(f"  [{item.get('key')}] {item.get('text', '')[:120]}")
    return 0


def cmd_memory_upsert(args: argparse.Namespace) -> int:
    root = get_studio_root()
    try:
        project_dir, data, position = _load_memory_context(root, args)
        pid = data.get("project") or resolve_project_id(root, getattr(args, "project", None))
        namespace = resolve_memory_namespace(args.namespace, pid)
    except (FileNotFoundError, ValueError, MemoryError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    text = args.text
    if args.file:
        text = Path(args.file).read_text(encoding="utf-8")
    if not text.strip():
        print("请提供 --text 或 --file", file=sys.stderr)
        return 1
    try:
        path = upsert(
            root,
            project_dir,
            position,
            namespace,
            args.key,
            text,
            project_id=pid,
        )
    except MemoryError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"[OK] 已写入: {path}")
    print(f"  命名空间: {namespace}")
    return 0


def build_parser(*, subparsers_required: bool = True) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="studio", description="IntAgent 协作开发管理平台")
    parser.add_argument("--plain", action="store_true", help="强制 plain CLI，不启动 TUI")
    sub = parser.add_subparsers(dest="command", required=subparsers_required)

    _register_init_parser(sub)
    _register_task_parser(sub)
    _register_status_parser(sub)
    _register_review_parser(sub)
    _register_project_parsers(sub)
    _register_skills_parser(sub)
    _register_mcp_parser(sub)
    _register_memory_parsers(sub)
    _register_org_parsers(sub)
    register_agent_commands(sub)
    _register_expand_parsers(sub)

    return parser


def _register_init_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("init", help="创建新项目")
    p.add_argument("--name", required=True, help="项目 id")
    p.add_argument("--path", default=None, help="项目文件夹（代码仓库根，.studio/ 存管理数据）")
    p.add_argument("--repo", default=None, help="同 --path（兼容旧参数）")
    p.add_argument("--description", default=None)
    p.set_defaults(func=cmd_init)


def _register_task_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("task", help="下达任务")
    p.add_argument("description", help="任务描述")
    p.add_argument("--project", default=None)
    p.add_argument("--orchestrate", action="store_true", help="完整编排+spawn")
    p.add_argument("--no-spawn", action="store_true")
    p.add_argument("--mock", action="store_true")
    p.set_defaults(func=cmd_task)


def _register_status_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("status", help="查看进度")
    p.add_argument("--project", default=None)
    p.set_defaults(func=cmd_status)


def _register_review_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("review", help="审批")
    p.add_argument("--project", default=None)
    p.add_argument("--task-id", default=None)
    p.add_argument("--verdict", choices=["approved", "rejected", "escalated"], default=None)
    p.set_defaults(func=cmd_review)


def _register_project_parsers(sub: argparse._SubParsersAction) -> None:
    p_project = sub.add_parser("project", help="项目增删改查")
    p_sub = p_project.add_subparsers(dest="project_command", required=True)

    p_list = p_sub.add_parser("list", help="列出项目")
    p_list.set_defaults(func=cmd_project_list)

    p_show = p_sub.add_parser("show", help="查看项目")
    p_show.add_argument("name", help="项目 id")
    p_show.set_defaults(func=cmd_project_show)

    p_update = p_sub.add_parser("update", help="更新项目 registry")
    p_update.add_argument("name", help="项目 id")
    p_update.add_argument("--display-name", default=None, help="显示名称")
    p_update.add_argument("--purpose", default=None, help="项目定位")
    p_update.add_argument("--path", default=None, help="项目文件夹")
    p_update.set_defaults(func=cmd_project_update)

    p_delete = p_sub.add_parser("delete", help="删除项目（含整个项目文件夹）")
    p_delete.add_argument("name", help="项目 id")
    p_delete.add_argument("--yes", action="store_true", help="确认删除（不可恢复）")
    p_delete.set_defaults(func=cmd_project_delete)


def _register_skills_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("skills", help="技能仓库")
    p_sub = p.add_subparsers(dest="skills_command", required=True)
    p_list = p_sub.add_parser("list", help="列出已注册技能")
    p_list.set_defaults(func=cmd_skills_list)


def _register_mcp_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("mcp", help="MCP 服务注册表")
    p_sub = p.add_subparsers(dest="mcp_command", required=True)
    p_list = p_sub.add_parser("list", help="列出已注册 MCP")
    p_list.set_defaults(func=cmd_mcp_list)


def _register_memory_parsers(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("memory", help="记忆中台")
    p_sub = p.add_subparsers(dest="memory_command", required=True)

    p_list = p_sub.add_parser("list", help="列出命名空间")
    p_list.set_defaults(func=cmd_memory_list)

    p_search = p_sub.add_parser("search", help="搜索记忆")
    p_search.add_argument("namespace", help="命名空间：project（当前项目）或 project/{项目id}")
    p_search.add_argument("query", help="关键词")
    p_search.add_argument("--project", default=None)
    p_search.add_argument("--position", default="laowang", help="以何岗位身份查询")
    p_search.add_argument("--limit", type=int, default=10)
    p_search.set_defaults(func=cmd_memory_search)

    p_upsert = p_sub.add_parser("upsert", help="写入记忆")
    p_upsert.add_argument("namespace", help="命名空间：project（当前项目）或 project/{项目id}")
    p_upsert.add_argument("key", help="键")
    p_upsert.add_argument("--text", default="", help="正文")
    p_upsert.add_argument("--file", default=None, help="从文件读取正文")
    p_upsert.add_argument("--project", default=None)
    p_upsert.add_argument("--position", default="laowang", help="以何岗位身份写入")
    p_upsert.set_defaults(func=cmd_memory_upsert)


def _register_org_parsers(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("org", help="组织树编辑")
    p_sub = p.add_subparsers(dest="org_command", required=True)

    p_show = p_sub.add_parser("show", help="显示组织树")
    p_show.add_argument("--project", default=None)
    p_show.set_defaults(func=cmd_org_show)

    p_add = p_sub.add_parser("add", help="添加岗位")
    p_add.add_argument("role", help="岗位 id，如 xiaomo")
    p_add.add_argument("--parent", default=None, help="上级 id")
    p_add.add_argument("--project", default=None)
    p_add.set_defaults(func=cmd_org_add)

    p_move = p_sub.add_parser("move", help="移动岗位")
    p_move.add_argument("node", help="要移动的岗位 id")
    p_move.add_argument("parent", help="新上级 id")
    p_move.add_argument("--project", default=None)
    p_move.set_defaults(func=cmd_org_move)

    p_rm = p_sub.add_parser("remove", help="删除岗位")
    p_rm.add_argument("node", help="岗位 id")
    p_rm.add_argument("--strategy", default="reassign_to_parent",
                      choices=["reassign_to_parent", "promote_children", "archive"])
    p_rm.add_argument("--project", default=None)
    p_rm.set_defaults(func=cmd_org_remove)


def _register_expand_parsers(sub: argparse._SubParsersAction) -> None:
    p_expand = sub.add_parser("expand", help="扩建公司（交互式或子命令）")
    p_expand.add_argument("--project", default=None)
    p_sub = p_expand.add_subparsers(dest="expand_command")

    p_biz = p_sub.add_parser("business", help="开新业务线")
    p_biz.add_argument("description", nargs="?", default=None, help="业务描述")
    p_biz.add_argument("--template", default=None)
    p_biz.add_argument("--yes", action="store_true", help="确认新增")
    p_biz.add_argument("--project", default=None)
    p_biz.set_defaults(func=cmd_expand_business)

    p_role = p_sub.add_parser("role", help="部门内加人")
    p_role.add_argument("role", help="岗位 id")
    p_role.add_argument("--parent", default=None)
    p_role.add_argument("--project", default=None)
    p_role.set_defaults(func=cmd_expand_role)

    p_mgr = p_sub.add_parser("manager", help="插入管理层")
    p_mgr.add_argument("--id", required=True, dest="id", help="新主管 id")
    p_mgr.add_argument("--name", default=None)
    p_mgr.add_argument("--title", default="组长")
    p_mgr.add_argument("--reports-to", required=True, dest="reports_to")
    p_mgr.add_argument("--children", required=True, help="下属 id，逗号分隔")
    p_mgr.add_argument("--agent", default="opencode")
    p_mgr.add_argument("--model", default="deepseek-v4-pro")
    p_mgr.add_argument("--project", default=None)
    p_mgr.set_defaults(func=cmd_expand_manager)

    p_expand.set_defaults(func=cmd_expand_interactive)


def main(argv: list[str] | None = None) -> int:
    # Windows GBK 终端无法输出中文/Unicode，强制 stdout/stderr 使用 UTF-8
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name)
        if hasattr(stream, "reconfigure") and (stream.encoding or "").lower() not in ("utf-8", "utf8"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    argv = argv if argv is not None else sys.argv[1:]
    # 无参数 → TUI
    if not argv:
        from cli.tui.app import run_studio_app

        return run_studio_app()
    parser = build_parser(subparsers_required=not (len(argv) == 1 and argv[0] == "--plain"))
    args = parser.parse_args(argv)
    if getattr(args, "command", None) is None and not args.plain:
        from cli.tui.app import run_studio_app

        return run_studio_app()
    if args.command is None:
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
