# core/supervisor_client.py — Supervisor 客户端（优先 Go gRPC，回退 Python 本地注册表）
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import yaml

from core.supervisor.registry import PortRegistry, ProcessRegistry


class SupervisorClient:
    """与 Go studio-supervisor 交互；Go 不可用时使用 Python 回退。"""

    def __init__(self, root: Path, address: str = "127.0.0.1:42000"):
        self.root = root.resolve()
        self.address = address
        self.studio_dir = self.root / ".studio"
        self.registry_dir = self.studio_dir / "registry"
        self._ports: PortRegistry | None = None
        self._procs: ProcessRegistry | None = None

    def _load_config(self) -> dict:
        cfg_path = self.root / "config" / "platform.yaml"
        if not cfg_path.exists():
            return {}
        return yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}

    def _init_local(self) -> None:
        self.registry_dir.mkdir(parents=True, exist_ok=True)
        cfg = self._load_config()
        port_range = cfg.get("supervisor", {}).get("port_range", [41000, 41999])
        self._ports = PortRegistry(
            self.registry_dir / "ports.json", port_range[0], port_range[1]
        )
        self._procs = ProcessRegistry(self.registry_dir / "processes.json")

    def ensure_running(self) -> None:
        """确保 Supervisor 就绪；写 supervisor.pid。"""
        self.studio_dir.mkdir(parents=True, exist_ok=True)
        pid_file = self.studio_dir / "supervisor.pid"
        bin_path = self.root / "supervisor" / "bin" / "studio-supervisor.exe"
        if bin_path.exists():
            if not pid_file.exists():
                subprocess.Popen(
                    [str(bin_path), "--root", str(self.root)],
                    cwd=self.root,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            return
        # Python 回退：当前进程充当 supervisor 逻辑
        if not pid_file.exists():
            pid_file.write_text(str(os.getpid()), encoding="utf-8")
        self._init_local()

    def health(self) -> bool:
        self.ensure_running()
        pid_file = self.studio_dir / "supervisor.pid"
        return pid_file.exists()

    def acquire_port(self, owner: str) -> int:
        self.ensure_running()
        if self._ports is None:
            self._init_local()
        assert self._ports is not None
        return self._ports.acquire(owner)

    def release_port(self, port: int) -> None:
        if self._ports is None:
            self._init_local()
        assert self._ports is not None
        self._ports.release(port)

    def register_process(self, position_id: str, pid: int) -> None:
        self.ensure_running()
        if self._procs is None:
            self._init_local()
        assert self._procs is not None
        self._procs.register(position_id, pid)

    def is_process_alive(self, position_id: str) -> bool:
        if self._procs is None:
            self._init_local()
        assert self._procs is not None
        return self._procs.is_alive(position_id)
