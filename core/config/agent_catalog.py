# core/config/agent_catalog.py — 热门 Agent 目录：安装检测与可打开性
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import yaml

from agents.command_cache import clear_agent_command_cache, resolve_agent_command_cached
from agents.execute import agent_launch_check_error
from agents.goose_env import _goose_config_paths, goose_provider_configured
from agents.path_refresh import refresh_windows_path_env
from agents.registry import load_agents_config
from agents.version_probe import (
    fetch_latest_version,
    npm_package_from_install,
    pip_package_from_install,
    probe_cli_version,
    probe_cli_version_at,
    version_is_newer,
)

# 已安装版本 overlay 缓存 TTL（秒）；日常浏览读缓存，按 R 才重新探测
_INSTALLED_VERSION_TTL = 30 * 60


@dataclass(frozen=True)
class AgentCatalogRow:
    """目录中的一条 Agent 记录（供 TUI / CLI 展示）。"""

    id: str
    agent_id: str | None
    name: str
    tagline: str
    command: str
    byok: bool
    installed: bool
    command_path: str | None
    openable: bool
    launch_ready: bool
    launch_error: str
    install_cmd: str
    apikey_hint: str
    rank: int
    needs_configure: bool = False
    installed_version: str | None = None
    latest_version: str | None = None
    update_available: bool = False
    version_args: str = "--version"


_catalog_cache: tuple[tuple[float, ...], list[AgentCatalogRow]] | None = None


def _config_mtimes(root: Path) -> tuple[float, ...]:
    agents_p = root / "config" / "agents.yaml"
    catalog_p = root / "config" / "agents_catalog.yaml"
    am = agents_p.stat().st_mtime if agents_p.is_file() else 0.0
    cm = catalog_p.stat().st_mtime if catalog_p.is_file() else 0.0
    goose_mt = 0.0
    for gp in _goose_config_paths():
        if gp.is_file():
            goose_mt = max(goose_mt, gp.stat().st_mtime)
    return am, cm, goose_mt


def load_agent_catalog_config(root: Path) -> list[dict[str, Any]]:
    """读取 config/agents_catalog.yaml 中的 catalog 列表。"""
    path = root / "config" / "agents_catalog.yaml"
    if not path.is_file():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    items = data.get("catalog")
    return items if isinstance(items, list) else []


def clear_catalog_build_cache() -> None:
    """仅丢弃目录构建缓存（不刷新 PATH / command 缓存）。"""
    global _catalog_cache
    _catalog_cache = None


def invalidate_agent_catalog_cache(*, refresh_path: bool = True) -> None:
    """用户按 R 刷新或安装完成后：可选刷新 PATH 并清解析缓存。"""
    clear_catalog_build_cache()
    if refresh_path:
        refresh_windows_path_env()
        clear_agent_command_cache()


def _catalog_probe_paths(raw: dict[str, Any]) -> list[str]:
    """catalog 条目可选的固定安装路径（MSI 等 PATH 尚未进当前进程时）。"""
    paths = raw.get("install_probe_paths") or raw.get("command_probe_paths") or []
    if isinstance(paths, str):
        paths = [paths]
    return [str(p).strip() for p in paths if p]


def _resolve_catalog_command(
    command: str,
    probe_paths: list[str],
    cache: dict[tuple[str, tuple[str, ...]], str | None],
) -> str | None:
    """PATH 解析 + 固定路径回退。"""
    key = (command, tuple(probe_paths))
    if key in cache:
        return cache[key]

    path = resolve_agent_command_cached(command) if command else None
    if not path:
        for raw_path in probe_paths:
            expanded = os.path.normpath(os.path.expandvars(raw_path))
            if os.path.isfile(expanded):
                path = expanded
                break

    cache[key] = path
    return path


def _installed_version_cache_path(root: Path) -> Path:
    return root / ".studio" / "cache" / "agent-installed-versions.json"


def _load_installed_version_cache(root: Path) -> dict[str, Any]:
    path = _installed_version_cache_path(root)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_installed_version_cache(root: Path, data: dict[str, Any]) -> None:
    path = _installed_version_cache_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _cached_installed_version(
    root: Path,
    entry_id: str,
    cmd_path: str,
    cache: dict[str, Any],
) -> str | None:
    """读磁盘缓存的已安装版本（按 exe mtime 校验）。"""
    hit = cache.get(entry_id)
    if not isinstance(hit, dict) or not hit.get("version"):
        return None
    try:
        exe_mtime = os.path.getmtime(cmd_path)
    except OSError:
        return None
    if float(hit.get("exe_mtime") or 0) != exe_mtime:
        return None
    if time.time() - float(hit.get("ts") or 0) > _INSTALLED_VERSION_TTL:
        return None
    return str(hit["version"])


def _probe_installed_version(
    root: Path,
    entry_id: str,
    command: str,
    cmd_path: str,
    version_args: str,
    cache: dict[str, Any],
    *,
    force_probe: bool,
) -> str | None:
    if not force_probe:
        cached = _cached_installed_version(root, entry_id, cmd_path, cache)
        if cached:
            return cached

    version = probe_cli_version(command, version_args) if command else None
    if not version:
        version = probe_cli_version_at(cmd_path, version_args)
    if not version:
        return _cached_installed_version(root, entry_id, cmd_path, cache)

    try:
        cache[entry_id] = {
            "version": version,
            "exe_mtime": os.path.getmtime(cmd_path),
            "ts": time.time(),
        }
    except OSError:
        cache[entry_id] = {"version": version, "ts": time.time()}
    return version


def _apply_version_overlay(rows: list[AgentCatalogRow], overlay: dict[str, Any]) -> list[AgentCatalogRow]:
    """快速构建后合并上次探测的版本信息（不阻塞 UI）。"""
    if not overlay:
        return rows
    out: list[AgentCatalogRow] = []
    for row in rows:
        hit = overlay.get(row.id)
        if not isinstance(hit, dict):
            out.append(row)
            continue
        installed_version = hit.get("installed_version") or row.installed_version
        latest_version = hit.get("latest_version") or row.latest_version
        update_available = bool(hit.get("update_available", row.update_available))
        if installed_version and latest_version:
            update_available = version_is_newer(str(latest_version), str(installed_version))
        out.append(
            replace(
                row,
                installed_version=installed_version,
                latest_version=latest_version,
                update_available=update_available,
            )
        )
    return out


def _save_version_overlay(root: Path, rows: list[AgentCatalogRow]) -> None:
    overlay = {
        row.id: {
            "installed_version": row.installed_version,
            "latest_version": row.latest_version,
            "update_available": row.update_available,
        }
        for row in rows
        if row.installed_version or row.latest_version
    }
    path = root / ".studio" / "cache" / "agent-catalog-version-overlay.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(overlay, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_version_overlay(root: Path) -> dict[str, Any]:
    path = root / ".studio" / "cache" / "agent-catalog-version-overlay.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def is_catalog_agent_installed(
    root: Path, entry_id: str, *, refresh_path: bool = False
) -> bool:
    """轻量检测单条 Agent 是否已安装（安装轮询用，不探测版本）。"""
    if refresh_path:
        refresh_windows_path_env()
        clear_agent_command_cache()

    raw = next(
        (item for item in load_agent_catalog_config(root) if str(item.get("id")) == entry_id),
        None,
    )
    if not isinstance(raw, dict):
        return False

    command = str(raw.get("command") or "").strip()
    probe_paths = _catalog_probe_paths(raw)
    path_cache: dict[tuple[str, tuple[str, ...]], str | None] = {}
    return bool(_resolve_catalog_command(command, probe_paths, path_cache))


def build_agent_catalog(
    root: Path,
    *,
    force: bool = False,
    refresh_path: bool = False,
    probe_versions: bool = False,
    network_versions: bool = False,
) -> list[AgentCatalogRow]:
    """合并目录配置与 PATH 检测。

    默认仅快速检测安装状态（毫秒级）；版本探测与 registry 查询仅在 probe_versions=True 时执行。
    """
    global _catalog_cache
    mtimes = _config_mtimes(root)
    if not force and _catalog_cache and _catalog_cache[0] == mtimes:
        rows = _catalog_cache[1]
        if probe_versions:
            return rows
        return _apply_version_overlay(rows, _load_version_overlay(root))

    if refresh_path:
        refresh_windows_path_env()
        clear_agent_command_cache()

    agents_cfg = load_agents_config(root).get("agents") or {}
    orchestratable = set(agents_cfg.keys())
    goose_ok = goose_provider_configured()
    version_disk = _load_installed_version_cache(root)
    version_dirty = False

    rows: list[AgentCatalogRow] = []
    path_cache: dict[tuple[str, tuple[str, ...]], str | None] = {}

    for raw in load_agent_catalog_config(root):
        if not isinstance(raw, dict):
            continue
        entry_id = str(raw.get("id") or "").strip()
        if not entry_id:
            continue

        command = str(raw.get("command") or "").strip()
        probe_paths = _catalog_probe_paths(raw)
        agent_id_raw = raw.get("agent_id")
        agent_id = str(agent_id_raw).strip() if agent_id_raw else None
        if agent_id == "null" or agent_id == "":
            agent_id = None

        cmd_path = _resolve_catalog_command(command, probe_paths, path_cache)
        installed = bool(cmd_path)
        openable = bool(agent_id and agent_id in orchestratable)
        launch_error = ""
        launch_ready = False
        if openable and installed and agent_id:
            cfg = agents_cfg.get(agent_id) or {}
            launch_error = agent_launch_check_error(str(cfg.get("command") or command), cmd_path)
            launch_ready = not launch_error

        needs_configure = agent_id == "goose" and installed and not goose_ok

        version_args = str(raw.get("version_args") or "--version")
        installed_version: str | None = None
        latest_version: str | None = None
        update_available = False

        if probe_versions and installed and cmd_path:
            installed_version = _probe_installed_version(
                root,
                entry_id,
                command,
                cmd_path,
                version_args,
                version_disk,
                force_probe=force,
            )
            version_dirty = True

        npm_pkg = str(raw.get("npm_package") or "") or npm_package_from_install(
            str(raw.get("install_cmd") or "")
        )
        pip_pkg = str(raw.get("pip_package") or "") or pip_package_from_install(
            str(raw.get("install_cmd") or "")
        )
        if probe_versions and (npm_pkg or pip_pkg):
            latest_version = fetch_latest_version(
                root,
                entry_id,
                npm_package=npm_pkg or None,
                pip_package=pip_pkg or None,
                force=force,
                allow_network=network_versions,
            )
        if installed_version and latest_version:
            update_available = version_is_newer(latest_version, installed_version)

        rows.append(
            AgentCatalogRow(
                id=entry_id,
                agent_id=agent_id,
                name=str(raw.get("name") or entry_id),
                tagline=str(raw.get("tagline") or ""),
                command=command,
                byok=bool(raw.get("byok")),
                installed=installed,
                command_path=cmd_path,
                openable=openable,
                launch_ready=launch_ready,
                launch_error=launch_error,
                install_cmd=str(raw.get("install_cmd") or ""),
                apikey_hint=str(raw.get("apikey_hint") or "在 Agent 终端内自行配置 API Key"),
                rank=int(raw.get("rank") or 999),
                needs_configure=needs_configure,
                installed_version=installed_version,
                latest_version=latest_version,
                update_available=update_available,
                version_args=version_args,
            )
        )

    rows.sort(key=lambda r: (r.rank, r.name))
    if version_dirty:
        _save_installed_version_cache(root, version_disk)
    if probe_versions:
        _save_version_overlay(root, rows)
        _catalog_cache = (mtimes, rows)
        return rows

    fast_rows = rows
    _catalog_cache = (mtimes, fast_rows)
    return _apply_version_overlay(fast_rows, _load_version_overlay(root))


def catalog_summary(rows: list[AgentCatalogRow]) -> dict[str, int]:
    """统计已安装 / 可打开数量。"""
    return {
        "total": len(rows),
        "installed": sum(1 for r in rows if r.installed),
        "openable_installed": sum(1 for r in rows if catalog_row_can_open(r)),
    }


def catalog_row_can_open(row: AgentCatalogRow) -> bool:
    """目录中该项是否应显示为可打开（含仅 catalog 展示、未写入 agents.yaml 的 CLI）。"""
    if not row.installed or row.needs_configure:
        return False
    if row.launch_ready:
        return True
    if row.command and not row.agent_id:
        return not agent_launch_check_error(row.command, row.command_path)
    if row.agent_id and row.openable and row.command:
        return not agent_launch_check_error(row.command, row.command_path)
    return False
