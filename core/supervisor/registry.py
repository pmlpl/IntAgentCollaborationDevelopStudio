# core/supervisor/registry.py — 端口租约与进程注册（与 Go supervisor 共用 JSON 格式）
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path


class PortRegistry:
    """中央端口租约表。"""

    def __init__(self, path: Path, min_port: int = 41000, max_port: int = 41999):
        self.path = path
        self.min_port = min_port
        self.max_port = max_port
        self._leases: dict[int, dict] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        for key, entry in data.get("leases", {}).items():
            self._leases[int(key)] = entry

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "leases": {str(port): entry for port, entry in self._leases.items()}
        }
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def acquire(self, owner: str) -> int:
        with self._lock:
            for port in range(self.min_port, self.max_port + 1):
                if port not in self._leases:
                    self._leases[port] = {"owner": owner, "port": port}
                    self._save()
                    return port
            raise RuntimeError(f"no free port in range {self.min_port}-{self.max_port}")

    def release(self, port: int) -> None:
        with self._lock:
            if port not in self._leases:
                raise KeyError(f"port {port} not leased")
            del self._leases[port]
            self._save()


class ProcessRegistry:
    """position_id 到 PID 的映射。"""

    def __init__(self, path: Path):
        self.path = path
        self._processes: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self._processes = data.get("processes", {})

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"processes": self._processes}
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def register(self, position_id: str, pid: int) -> None:
        with self._lock:
            self._processes[position_id] = {
                "position_id": position_id,
                "pid": pid,
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
            self._save()

    def unregister(self, position_id: str) -> None:
        with self._lock:
            self._processes.pop(position_id, None)
            self._save()

    def is_alive(self, position_id: str) -> bool:
        entry = self._processes.get(position_id)
        if not entry:
            return False
        try:
            os.kill(entry["pid"], 0)
            return True
        except OSError:
            return False
