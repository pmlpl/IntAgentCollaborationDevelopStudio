# cli/agent_cli.py — 打开 / 检测各 Agent 交互 TUI 窗口
from __future__ import annotations

import argparse
import time
from pathlib import Path

from agents.registry import load_agents_config
from core.config.agent_catalog import build_agent_catalog, catalog_summary
from core.config.agent_policy import agent_allowed, agent_auto_detect, agent_enabled, set_agent_enabled
from core.project import get_project_root, get_studio_root, load_project, resolve_project_id
from core.terminal.agent_launcher import list_agent_tui_status, spawn_agent_tui, spawn_position_tui


def cmd_agent_status(args: argparse.Namespace) -> int:
    """列出 agents.yaml 中各 Agent CLI 是否在 PATH 中可用，以及启用/禁用状态。"""
    root = get_studio_root()
    rows = list_agent_tui_status(root)
    if not rows:
        print("未找到 config/agents.yaml 中的 Agent 配置。")
        return 1
    policy_note = ""
    if rows:
        policy_note = f"  策略: {rows[0].get('policy', 'all')}"
    for row in rows:
        mark = "OK" if row["available"] else "--"
        byok = "BYOK" if row.get("byok") else "订阅"
        use = "可用" if row.get("allowed") else "禁用"
        enable_mark = "[启用]" if agent_enabled(root, row["id"]) else "[禁用]"
        print(
            f"  [{mark}] {row['id']:12} {row['name']:14} "
            f"{byok:4} {use:4} {enable_mark} command={row['command']}"
        )
    ok = sum(1 for r in rows if r["available"] and r.get("allowed"))
    total_allowed = sum(1 for r in rows if r.get("allowed"))
    total_enabled = sum(1 for r in rows if agent_enabled(root, r["id"]))
    print(f"\nCLI 可用 {ok}/{total_allowed}（策略允许）· 已启用 {total_enabled}/{len(rows)}")
    print(f"策略: {policy_note}")
    return 0 if ok else 1


def cmd_agent_list(_args: argparse.Namespace) -> int:
    """列出热门 Agent 目录及安装状态（与 Studio TUI「Agent 目录」相同数据）。"""
    root = get_studio_root()
    rows = build_agent_catalog(root)
    if not rows:
        print("未找到 config/agents_catalog.yaml。")
        return 1
    stats = catalog_summary(rows)
    print(f"热门 Agent 目录 · 已安装 {stats['installed']}/{stats['total']}\n")
    for row in rows:
        if row.installed:
            mark = "OK"
        else:
            mark = "--"
        byok = "BYOK" if row.byok else "订阅"
        openable = "可打开" if row.openable else "仅展示"
        print(f"  [{mark}] {row.name:18} {byok:4} {openable:6}  {row.command}")
        if row.tagline:
            print(f"       {row.tagline}")
        if not row.installed and row.install_cmd:
            print(f"       安装: {row.install_cmd}")
    print("\n在 Studio 中按 A 或点「Agent 目录」可打开已安装的 Agent TUI。")
    return 0


def cmd_agent_open(args: argparse.Namespace) -> int:
    """打开一个或多个 Agent 的交互 TUI 窗口。"""
    root = get_studio_root()
    project_id = args.project or resolve_project_id(root)
    project_dir = load_project(root, project_id)
    cwd = Path(args.cwd).resolve() if args.cwd else get_project_root(root, project_id)

    if args.all:
        agents_cfg = load_agents_config(get_studio_root()).get("agents", {})
        agent_ids = [aid for aid in agents_cfg if agent_allowed(root, aid)]
        opened = 0
        for agent_id in agent_ids:
            cfg = agents_cfg[agent_id]
            name = cfg.get("name", agent_id)
            try:
                spawn_agent_tui(
                    root,
                    agent_id,
                    cwd,
                    title=f"Studio · {name}",
                    prompt=f"这是 {name} 的 TUI 连通性测试。请确认你已进入全屏交互界面。",
                    role=name,
                    respect_policy=False,
                )
                print(f"OK 已打开 {agent_id}")
                opened += 1
                time.sleep(0.4)
            except RuntimeError as exc:
                print(f"-- 跳过 {agent_id}: {exc}")
        print(f"\n已尝试打开 {opened}/{len(agent_ids)} 个窗口")
        return 0 if opened else 1

    if args.position:
        pos_id = args.position
        prompt = args.prompt or "Studio 已打开你的 Agent 窗口，请等待任务或开始工作。"
        spawn_position_tui(
            root,
            project_dir,
            pos_id,
            cwd,
            prompt=prompt,
        )
        print(f"OK 已打开岗位 {pos_id} 的 Agent TUI")
        return 0

    agent_id = args.agent_id or "opencode"
    prompt = args.prompt or f"Studio 已打开 {agent_id} 交互窗口。"
    spawn_agent_tui(
        root,
        agent_id,
        cwd,
        title=f"Studio · {agent_id}",
        prompt=prompt,
        role=agent_id,
        respect_policy=False,
    )
    print(f"OK 已打开 Agent {agent_id}")
    return 0


def cmd_agent_enable(args: argparse.Namespace) -> int:
    """启用指定 Agent（允许被 Studio 调度）。"""
    root = get_studio_root()
    agents_cfg = load_agents_config(root).get("agents", {})
    if args.agent_id not in agents_cfg:
        print(f"未知 Agent: {args.agent_id}", file=__import__("sys").stderr)
        return 1
    set_agent_enabled(root, args.agent_id, True)
    available = agent_enabled(root, args.agent_id)
    avail_str = "CLI 可用" if available else "CLI 不在 PATH（仅策略放行，无法启动）"
    print(f"✓ 已启用 {args.agent_id} ({avail_str})")
    return 0


def cmd_agent_disable(args: argparse.Namespace) -> int:
    """禁用指定 Agent（不会启动，自动走 mock）。"""
    root = get_studio_root()
    agents_cfg = load_agents_config(root).get("agents", {})
    if args.agent_id not in agents_cfg:
        print(f"未知 Agent: {args.agent_id}", file=__import__("sys").stderr)
        return 1
    set_agent_enabled(root, args.agent_id, False)
    print(f"✓ 已禁用 {args.agent_id}（调度时将自动走 mock）")
    return 0


def cmd_agent_detect(args: argparse.Namespace) -> int:
    """自动检测已安装的 Agent CLI 并显示启用状态。"""
    root = get_studio_root()
    status = agent_auto_detect(root)
    if not status:
        print("未在 agents.yaml 中找到任何 Agent 配置。")
        return 1
    installed = 0
    for agent_id, available in sorted(status.items()):
        enabled = agent_enabled(root, agent_id)
        mark = "✓" if available else "✗"
        state = "[已启用]" if enabled else "[已禁用]"
        print(f"  [{mark}] {agent_id:16} 安装={'是' if available else '否':3}  {state}")
        if available:
            installed += 1
    print(f"\n已安装 {installed}/{len(status)} 个 Agent CLI")
    print("已安装的默认启用，未安装的默认禁用（auto_detect=true）")
    return 0


def cmd_agent_check(args: argparse.Namespace) -> int:
    """对指定（或全部）Agent 执行健康检查：PATH → --version → 冒烟。"""
    from agents.health import check_agent, check_all_agents

    root = get_studio_root()
    agents_cfg = load_agents_config(root).get("agents", {})

    if args.agent_id:
        if args.agent_id not in agents_cfg:
            print(f"未知 Agent: {args.agent_id}", file=__import__("sys").stderr)
            return 1
        report = check_agent(root, args.agent_id, smoke=not args.no_smoke, cwd=Path.cwd())
        _print_health_report(report, verbose=args.verbose)
        return 0 if report.healthy else 1
    else:
        reports = check_all_agents(root, smoke=not args.no_smoke, cwd=Path.cwd())
        ok = 0
        for agent_id, report in reports.items():
            _print_health_report(report, verbose=args.verbose)
            if report.healthy:
                ok += 1
        degraded = sum(1 for r in reports.values() if r.overall == "degraded")
        unavailable = sum(1 for r in reports.values() if r.overall == "unavailable")
        print(f"\nHealthy: {ok}/{len(reports)}  Degraded: {degraded}  Unavailable: {unavailable}")
        return 0 if ok == len(reports) else 1


def _print_health_report(report, *, verbose: bool = False) -> None:
    """格式化打印 AgentHealthReport。"""
    from agents.health import AgentHealthReport

    status_icon = {"ok": "[OK]", "degraded": "[!!]", "unavailable": "[XX]"}
    icon = status_icon.get(report.overall, "[??]")

    print(f"\n{icon} {report.agent_id} [{report.overall}]")
    if report.command:
        print(f"  command: {report.command}")
    if report.resolved_path:
        print(f"  path: {report.resolved_path}")

    for check in report.checks:
        mark = "OK" if check["ok"] else "!!"
        detail = str(check["detail"])[:150]
        print(f"  [{mark}] {check['check']}: {detail}")

    if report.api_key_ok is False:
        print(f"  ⚠ API key 未配置或无效（Agent CLI 可能无法真正工作）")

    if verbose:
        if report.version:
            print(f"  version output ({len(report.version)} chars):")
            for line in report.version.splitlines()[:5]:
                print(f"    | {line[:120]}")
        if report.smoke_output:
            print(f"  smoke output ({len(report.smoke_output)} chars):")
            for line in report.smoke_output.splitlines()[:5]:
                print(f"    | {line[:120]}")


def register_agent_commands(sub) -> None:
    """注册 studio agent 子命令。"""
    p_agent = sub.add_parser("agent", help="Agent 交互 TUI（打开窗口 / 检测 CLI / 启用禁用）")
    p_agent_sub = p_agent.add_subparsers(dest="agent_command", required=True)

    p_status = p_agent_sub.add_parser("status", help="检测各 Agent CLI 是否在 PATH 以及启用/禁用状态")
    p_status.set_defaults(func=cmd_agent_status)

    p_list = p_agent_sub.add_parser("list", help="热门 Agent 目录（安装状态 / 安装命令）")
    p_list.set_defaults(func=cmd_agent_list)

    p_check = p_agent_sub.add_parser("check", help="Agent 健康检查（PATH → --version → 冒烟）")
    p_check.add_argument("agent_id", nargs="?", help="要检查的 Agent ID，不指定则检查全部")
    p_check.add_argument("--no-smoke", action="store_true", help="跳过冒烟测试（仅 --version）")
    p_check.add_argument("--verbose", "-v", action="store_true", help="显示详细输出")
    p_check.set_defaults(func=cmd_agent_check)

    p_open = p_agent_sub.add_parser("open", help="打开 Agent 交互 TUI 窗口")
    p_open.add_argument("agent_id", nargs="?", help="agents.yaml 中的 id，如 claude-code")
    p_open.add_argument("--all", action="store_true", help="依次打开所有可用 Agent TUI")
    p_open.add_argument("--position", "-p", help="按岗位 id 打开（使用岗位配置的 agent）")
    p_open.add_argument("--project", help="项目 id")
    p_open.add_argument("--cwd", help="工作目录（默认项目根）")
    p_open.add_argument("--prompt", help="写入 .studio/STUDIO_TASK.md 的说明")
    p_open.set_defaults(func=cmd_agent_open)

    p_enable = p_agent_sub.add_parser("enable", help="启用 Agent（允许被 Studio 调度）")
    p_enable.add_argument("agent_id", help="要启用的 Agent ID，如 opencode")
    p_enable.set_defaults(func=cmd_agent_enable)

    p_disable = p_agent_sub.add_parser("disable", help="禁用 Agent（调度时自动走 mock）")
    p_disable.add_argument("agent_id", help="要禁用的 Agent ID，如 claude-code")
    p_disable.set_defaults(func=cmd_agent_disable)

    p_detect = p_agent_sub.add_parser("detect", help="自动检测已安装的 Agent CLI 并显示启用状态")
    p_detect.set_defaults(func=cmd_agent_detect)
