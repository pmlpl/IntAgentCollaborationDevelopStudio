# agents/goose_env.py — Goose CLI 配置状态检测
from __future__ import annotations

import os
from pathlib import Path

import yaml

GOOSE_CONFIGURE_CMD = "goose configure"


def _goose_config_paths() -> list[Path]:
    """Goose 配置文件可能位置（Windows / Unix）。"""
    paths: list[Path] = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        paths.append(Path(appdata) / "Block" / "goose" / "config" / "config.yaml")
        paths.append(Path(appdata) / "goose" / "config.yaml")
    paths.append(Path.home() / ".config" / "goose" / "config.yaml")
    return paths


def _config_has_provider(data: dict) -> bool:
    """config.yaml 中是否已设置 LLM provider（兼容新旧 Goose 格式）。"""
    if not data:
        return False

    for key in ("GOOSE_PROVIDER", "provider", "model_provider"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return True

    # Goose 新版：active_provider + providers.custom_xxx.configured
    active = data.get("active_provider")
    providers = data.get("providers")
    if isinstance(active, str) and active.strip():
        if isinstance(providers, dict):
            entry = providers.get(active.strip())
            if isinstance(entry, dict):
                if entry.get("configured") is True:
                    return True
                if entry.get("enabled") is True and str(entry.get("model") or "").strip():
                    return True
        # 有 active_provider 且无 providers 段时也视为已配置
        if not isinstance(providers, dict):
            return True

    if isinstance(providers, dict):
        for entry in providers.values():
            if not isinstance(entry, dict):
                continue
            if entry.get("configured") is True:
                return True
            if entry.get("enabled") is True and str(entry.get("model") or "").strip():
                return True

    profiles = data.get("profiles")
    if isinstance(profiles, dict):
        for prof in profiles.values():
            if isinstance(prof, dict):
                p = prof.get("provider") or prof.get("GOOSE_PROVIDER")
                if isinstance(p, str) and p.strip():
                    return True
    return False


def goose_provider_configured() -> bool:
    """Goose 是否已完成 provider 配置（否则 session 会立即退出）。"""
    if os.environ.get("GOOSE_PROVIDER", "").strip():
        return True
    for path in _goose_config_paths():
        if not path.is_file():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except OSError:
            continue
        if _config_has_provider(data if isinstance(data, dict) else {}):
            return True
    return False


def goose_setup_command() -> str:
    """首次使用 Goose 时在终端执行的配置命令。"""
    return GOOSE_CONFIGURE_CMD
