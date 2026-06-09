# agents/path_refresh.py — Windows 下刷新进程 PATH（MSI/npm 安装后 Studio 仍能检测新命令）
from __future__ import annotations

import os


def refresh_windows_path_env() -> bool:
    """从注册表重读 User + Machine PATH 写回 os.environ；非 Windows 无操作。"""
    if os.name != "nt":
        return False
    try:
        import winreg
    except ImportError:
        return False

    parts: list[str] = []

    def _read_path(root: int, subkey: str) -> str:
        try:
            with winreg.OpenKey(root, subkey) as key:
                value, _ = winreg.QueryValueEx(key, "Path")
                return str(value or "")
        except OSError:
            return ""

    user_path = _read_path(winreg.HKEY_CURRENT_USER, "Environment")
    machine_path = _read_path(
        winreg.HKEY_LOCAL_MACHINE,
        r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
    )
    if machine_path:
        parts.append(os.path.expandvars(machine_path))
    if user_path:
        parts.append(os.path.expandvars(user_path))

    if not parts:
        return False

    os.environ["PATH"] = os.pathsep.join(parts)
    return True
