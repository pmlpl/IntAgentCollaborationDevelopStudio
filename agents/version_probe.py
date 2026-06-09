# agents/version_probe.py — Agent CLI 版本探测与 registry 最新版查询
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from agents.execute import CAPTURE_TEXT_KW, prepare_subprocess_argv, resolve_agent_command

# registry 最新版本缓存 TTL（秒）
_LATEST_CACHE_TTL = 6 * 3600


def _normalize_version(text: str) -> str:
    """从 CLI 输出中提取 semver 样版本号。"""
    text = text.strip()
    if not text:
        return ""
    match = re.search(r"(\d+\.\d+\.\d+(?:[-+][\w.]+)?)", text)
    if match:
        return match.group(1)
    # 单行输出整段作为版本（如 goose 1.2.3）
    first = text.splitlines()[0].strip()
    if re.match(r"^v?\d", first):
        return first.lstrip("v")
    return first[:40]


def npm_package_from_install(install_cmd: str) -> str | None:
    """从 npm install -g pkg 解析包名。"""
    match = re.search(r"npm\s+install\s+(?:-g|--global)\s+(\S+)", install_cmd, re.I)
    return match.group(1) if match else None


def pip_package_from_install(install_cmd: str) -> str | None:
    """从 pip install pkg 解析包名。"""
    match = re.search(
        r"pip3?\s+install\s+(?:-U\s+|--upgrade\s+)?(\S+)", install_cmd, re.I
    )
    if not match:
        return None
    pkg = match.group(1)
    if pkg.startswith("-"):
        return None
    return pkg


def probe_cli_version(command: str, version_args: str = "--version") -> str | None:
    """运行 command --version 获取已安装版本；未安装或失败返回 None。"""
    if not command or not resolve_agent_command(command):
        return None
    try:
        # Windows npm 全局命令需解析 .cmd/.exe，不能直接用裸命令名
        argv = prepare_subprocess_argv(
            [command, *version_args.split()],
            interactive=False,
        )
        return _run_version_probe(argv)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def probe_cli_version_at(resolved_path: str, version_args: str = "--version") -> str | None:
    """对已解析的 exe/.cmd 路径探测版本（MSI 固定目录等 PATH 未刷新时）。"""
    if not resolved_path or not os.path.isfile(resolved_path):
        return None
    try:
        argv = prepare_subprocess_argv(
            [resolved_path, *version_args.split()],
            interactive=False,
        )
        return _run_version_probe(argv)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def _run_version_probe(argv: list[str]) -> str | None:
    try:
        proc = subprocess.run(argv, **CAPTURE_TEXT_KW, timeout=4)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 and not (proc.stdout or proc.stderr):
        return None
    out = (proc.stdout or proc.stderr or "").strip()
    if not out:
        return None
    return _normalize_version(out)


def _fetch_npm_latest(package: str) -> str | None:
    try:
        proc = subprocess.run(
            ["npm", "view", package, "version"],
            **CAPTURE_TEXT_KW,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    ver = (proc.stdout or "").strip()
    return ver or None


def _fetch_pip_latest(package: str) -> str | None:
    try:
        proc = subprocess.run(
            ["pip", "index", "versions", package],
            **CAPTURE_TEXT_KW,
            timeout=25,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    # pip index versions: pkg (1.2.3, 1.2.2, ...)
    text = proc.stdout or ""
    match = re.search(r"\(([\d.]+)", text)
    if match:
        return match.group(1)
    match = re.search(r"(\d+\.\d+\.\d+)", text)
    return match.group(1) if match else None


def _cache_path(studio_root: Path) -> Path:
    return studio_root / ".studio" / "cache" / "agent-latest-versions.json"


def _load_latest_cache(studio_root: Path) -> dict[str, Any]:
    path = _cache_path(studio_root)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_latest_cache(studio_root: Path, data: dict[str, Any]) -> None:
    path = _cache_path(studio_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_latest_version(
    studio_root: Path,
    cache_key: str,
    *,
    npm_package: str | None = None,
    pip_package: str | None = None,
    force: bool = False,
    allow_network: bool = True,
) -> str | None:
    """查询 registry 最新版本（带本地 JSON 缓存）。"""
    if not npm_package and not pip_package:
        return None
    cache = _load_latest_cache(studio_root)
    now = time.time()
    hit = cache.get(cache_key)
    if (
        not force
        and isinstance(hit, dict)
        and hit.get("version")
        and now - float(hit.get("ts") or 0) < _LATEST_CACHE_TTL
    ):
        return str(hit["version"])

    if not allow_network and not force:
        return str(hit["version"]) if isinstance(hit, dict) and hit.get("version") else None

    latest: str | None = None
    if npm_package:
        latest = _fetch_npm_latest(npm_package)
    if not latest and pip_package:
        latest = _fetch_pip_latest(pip_package)

    if latest:
        cache[cache_key] = {"version": latest, "ts": now}
        _save_latest_cache(studio_root, cache)
    return latest


def version_is_newer(latest: str, current: str) -> bool:
    """粗略比较版本号；无法解析时按字符串不等判断。"""
    if not latest or not current:
        return False
    if latest.strip() == current.strip():
        return False

    def _parts(v: str) -> list[int]:
        nums = re.findall(r"\d+", v)
        return [int(x) for x in nums[:4]] if nums else []

    lp, cp = _parts(latest), _parts(current)
    if lp and cp:
        n = max(len(lp), len(cp))
        lp.extend([0] * (n - len(lp)))
        cp.extend([0] * (n - len(cp)))
        return lp > cp
    return latest != current
