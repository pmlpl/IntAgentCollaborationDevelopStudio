# core/config/agent_policy.py — Agent 选用策略（BYOK / 第三方模型 / 启用控制）
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import yaml

from agents.registry import load_agents_config
from agents.runner import agent_available

POLICY_ALL = "all"
POLICY_BYOK_ONLY = "byok_only"

# agent_enabled 结果缓存，避免每次刷新 TUI 都扫 PATH
_enabled_cache: dict[str, dict[str, bool]] = {}
_enabled_cache_time: dict[str, float] = {}
_CACHE_TTL = 30.0  # 秒


def _load_platform_agents_section(root: Path) -> dict[str, Any]:
    path = root / "config" / "platform.yaml"
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    section = data.get("agents")
    return section if isinstance(section, dict) else {}


def _save_platform_agents_section(root: Path, section: dict[str, Any]) -> None:
    """写入 platform.yaml 的 agents 段，保留其他 section 不变。"""
    path = root / "config" / "platform.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data["agents"] = section
    path.write_text(yaml.dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def agent_policy(root: Path) -> str:
    """当前策略：all=全部 | byok_only=仅允许 byok:true 的 Agent。"""
    return str(_load_platform_agents_section(root).get("policy") or POLICY_BYOK_ONLY)


def agent_is_byok(cfg: dict[str, Any]) -> bool:
    """agents.yaml 中 byok:true 表示可接 DeepSeek/Ollama/自建 API 等第三方模型。"""
    return bool(cfg.get("byok"))


def agent_enabled(root: Path, agent_id: str) -> bool:
    """检查 Agent 是否未被显式禁用（用户可在 TUI Agent 列表或 CLI 中开关）。

    auto_detect=true 时：已安装的 Agent 默认启用，未安装的默认禁用。
    显式加入 disabled 列表的 Agent 无论如何都被禁用。

    结果会缓存 30 秒，避免每次 TUI 刷新都扫 PATH（agent_available 会调 which）。
    """
    import time as _time

    root_str = str(root)
    now = _time.time()
    if root_str in _enabled_cache and (now - _enabled_cache_time.get(root_str, 0)) < _CACHE_TTL:
        return _enabled_cache[root_str].get(agent_id, True)

    agent_dict = _build_enabled_dict(root)
    _enabled_cache[root_str] = agent_dict
    _enabled_cache_time[root_str] = now
    return agent_dict.get(agent_id, True)


def _build_enabled_dict(root: Path) -> dict[str, bool]:
    """一次性构建所有 Agent 的启用状态，避免逐个调 agent_available。"""
    section = _load_platform_agents_section(root)
    disabled: list[str] = list(section.get("disabled") or [])
    auto_detect = section.get("auto_detect", True)
    agents = load_agents_config(root).get("agents", {})
    result: dict[str, bool] = {}
    for aid in agents:
        if aid in disabled:
            result[aid] = False
        elif auto_detect:
            result[aid] = agent_available(root, aid)
        else:
            result[aid] = True
    return result


def invalidate_enabled_cache(root: str | None = None) -> None:
    """使启用状态缓存失效（禁用/启用操作后调用）。"""
    if root is not None:
        _enabled_cache.pop(root, None)
        _enabled_cache_time.pop(root, None)
    else:
        _enabled_cache.clear()
        _enabled_cache_time.clear()


def agent_auto_detect(root: Path) -> dict[str, bool]:
    """扫描 PATH 中所有已注册 Agent CLI 的可用状态。

    返回 {agent_id: is_available}。
    """
    agents = load_agents_config(root).get("agents", {})
    result: dict[str, bool] = {}
    for agent_id, _cfg in agents.items():
        result[agent_id] = agent_available(root, agent_id)
    return result


def set_agent_enabled(root: Path, agent_id: str, enabled: bool) -> bool:
    """启用/禁用一个 Agent。返回操作后该 Agent 的状态。

    - enabled=True：从 disabled 列表中移除
    - enabled=False：添加到 disabled 列表
    """
    section = _load_platform_agents_section(root)
    disabled: list[str] = list(section.get("disabled") or [])

    if enabled:
        if agent_id in disabled:
            disabled.remove(agent_id)
    else:
        if agent_id not in disabled:
            disabled.append(agent_id)

    section["disabled"] = disabled
    _save_platform_agents_section(root, section)
    invalidate_enabled_cache(str(root))  # 立即生效，无需等 30s TTL
    return enabled


def agent_allowed(root: Path, agent_id: str) -> bool:
    """按 platform 策略 + 启用状态判断该 Agent 是否允许被 Studio 调度。

    Agent 可调度条件（全部满足）：
    1. 在 agents.yaml 中注册
    2. 未被显式禁用
    3. 如果 policy=byok_only，则 byok=true
    """
    cfg = load_agents_config(root).get("agents", {}).get(agent_id)
    if not cfg:
        return False
    if not agent_enabled(root, agent_id):
        return False
    if agent_policy(root) == POLICY_ALL:
        return True
    return agent_is_byok(cfg)


def default_byok_agent_id(root: Path) -> str:
    """平台默认 BYOK Agent（platform.yaml agents.default）。"""
    return str(_load_platform_agents_section(root).get("default") or "opencode")


def pick_spawn_agent_id(root: Path, preferred: str) -> str:
    """在 preferred 不被策略允许时，回退到可用的 BYOK Agent。"""
    if agent_allowed(root, preferred) and agent_available(root, preferred):
        return preferred

    section = _load_platform_agents_section(root)
    candidates: list[str] = []
    for aid in section.get("fallback_order") or []:
        candidates.append(str(aid))
    default = default_byok_agent_id(root)
    if default not in candidates:
        candidates.insert(0, default)

    for aid in candidates:
        if agent_allowed(root, aid) and agent_available(root, aid):
            return aid

    agents = load_agents_config(root).get("agents", {})
    for aid, meta in agents.items():
        if agent_is_byok(meta) and agent_available(root, aid):
            return aid

    raise RuntimeError(
        "没有可用的 BYOK Agent（需 byok:true 且 CLI 在 PATH 中）。"
        "请安装 opencode / hermes / aider / goose 并配置第三方模型，见 docs/INSTALL-AGENTS.md"
    )


def list_agents_for_ui(root: Path) -> list[tuple[str, str]]:
    """TUI 岗位编辑等场景：按策略过滤后的 (id, 显示名)。"""
    agents = load_agents_config(root).get("agents", {})
    items: list[tuple[str, str]] = []
    for aid, meta in agents.items():
        if agent_policy(root) == POLICY_BYOK_ONLY and not agent_is_byok(meta):
            continue
        label = meta.get("name") or aid
        items.append((aid, f"{label} ({aid})"))
    return items


def agent_can_execute(root: Path, agent_id: str) -> tuple[bool, str]:
    """检查 Agent 是否可以真正执行任务。

    综合检查 CLI 可用性、启用状态、BYOK 策略。
    返回 (can_execute, reason)。can_execute=False 时 reason 说明原因。
    供 agent_worker / dispatcher 共用，避免各处重复相同的检查链。
    """
    if not agent_id:
        return False, "未配置 Agent"
    if not agent_available(root, agent_id):
        return False, "CLI 命令不在 PATH 中"
    if not agent_enabled(root, agent_id):
        return False, "已被用户禁用"
    if not agent_allowed(root, agent_id):
        return False, "当前 BYOK 策略不允许"
    return True, "ok"
