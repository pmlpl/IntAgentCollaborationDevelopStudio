# core/supervisor_client.py — Supervisor 客户端（优先 Go gRPC，回退 Python 本地注册表）
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import yaml

from core.supervisor.registry import PortRegistry, ProcessRegistry

try:
    import grpc

    from core.supervisor.grpc import supervisor_pb2, supervisor_pb2_grpc

    _GRPC_AVAILABLE = True
except Exception:  # pragma: no cover - 无 grpc 或版本不匹配时回退
    _GRPC_AVAILABLE = False
    grpc = None  # type: ignore[assignment]
    supervisor_pb2 = None  # type: ignore[assignment]
    supervisor_pb2_grpc = None  # type: ignore[assignment]


class SupervisorClient:
    """与 Go studio-supervisor 交互；Go 不可用时使用 Python 回退。"""

    def __init__(self, root: Path, address: str = "127.0.0.1:42000"):
        self.root = root.resolve()
        self.address = address
        self.studio_dir = self.root / ".studio"
        self.registry_dir = self.studio_dir / "registry"
        self._ports: PortRegistry | None = None
        self._procs: ProcessRegistry | None = None
        self._stub = None
        self._channel = None

    def _load_config(self) -> dict:
        cfg_path = self.root / "config" / "platform.yaml"
        if not cfg_path.exists():
            return {}
        return yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}

    def _supervisor_bin(self) -> Path:
        return self.root / "supervisor" / "bin" / "studio-supervisor.exe"

    def _init_local(self) -> None:
        self.registry_dir.mkdir(parents=True, exist_ok=True)
        cfg = self._load_config()
        port_range = cfg.get("supervisor", {}).get("port_range", [41000, 41999])
        self._ports = PortRegistry(
            self.registry_dir / "ports.json", port_range[0], port_range[1]
        )
        self._procs = ProcessRegistry(self.registry_dir / "processes.json")

    def use_grpc(self) -> bool:
        """Go 二进制存在且 gRPC 可用。"""
        return _GRPC_AVAILABLE and self._supervisor_bin().exists()

    def _get_stub(self):
        if not self.use_grpc():
            return None
        if self._stub is None:
            assert grpc is not None
            self._channel = grpc.insecure_channel(self.address)
            self._stub = supervisor_pb2_grpc.SupervisorStub(self._channel)
        return self._stub

    def _grpc_health(self) -> bool:
        stub = self._get_stub()
        if stub is None:
            return False
        try:
            resp = stub.Health(supervisor_pb2.HealthRequest(), timeout=1.5)
            return bool(resp.ok)
        except Exception:
            return False

    def ensure_running(self) -> None:
        """确保 Supervisor 就绪；写 supervisor.pid。"""
        self.studio_dir.mkdir(parents=True, exist_ok=True)
        pid_file = self.studio_dir / "supervisor.pid"
        bin_path = self._supervisor_bin()
        if bin_path.exists():
            if not self._grpc_health():
                if pid_file.exists():
                    try:
                        pid_file.unlink()
                    except OSError:
                        pass
                subprocess.Popen(
                    [str(bin_path), "--root", str(self.root), "--addr", self.address],
                    cwd=self.root,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                    if os.name == "nt"
                    else 0,
                )
                for _ in range(30):
                    if self._grpc_health():
                        break
                    time.sleep(0.1)
            return
        if not pid_file.exists():
            pid_file.write_text(str(os.getpid()), encoding="utf-8")
        self._init_local()

    def health(self) -> bool:
        self.ensure_running()
        if self.use_grpc():
            return self._grpc_health()
        pid_file = self.studio_dir / "supervisor.pid"
        return pid_file.exists()

    def acquire_port(self, owner: str) -> int:
        self.ensure_running()
        stub = self._get_stub()
        if stub is not None:
            resp = stub.AcquirePort(supervisor_pb2.AcquirePortRequest(owner=owner), timeout=5)
            return int(resp.port)
        if self._ports is None:
            self._init_local()
        assert self._ports is not None
        return self._ports.acquire(owner)

    def release_port(self, port: int) -> None:
        stub = self._get_stub()
        if stub is not None:
            stub.ReleasePort(supervisor_pb2.ReleasePortRequest(port=port), timeout=5)
            return
        if self._ports is None:
            self._init_local()
        assert self._ports is not None
        self._ports.release(port)

    def spawn_agent(
        self,
        position_id: str,
        command: list[str],
        cwd: Path,
        env: dict[str, str] | None = None,
        *,
        project_id: str = "",
    ) -> int:
        """通过 Supervisor 启动 Agent 进程并注册 PID。"""
        self.ensure_running()
        stub = self._get_stub()
        merged_env = {k: str(v) for k, v in (env or {}).items()}
        if stub is not None:
            resp = stub.SpawnAgent(
                supervisor_pb2.SpawnAgentRequest(
                    position_id=position_id,
                    project_id=project_id,
                    worktree_path=str(cwd),
                    command=command,
                    env=merged_env,
                ),
                timeout=30,
            )
            return int(resp.pid)

        if self._procs is None:
            self._init_local()
        merged = os.environ.copy()
        merged.update(merged_env)
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        proc = subprocess.Popen(
            command,
            cwd=cwd,
            env=merged,
            creationflags=flags,
        )
        assert self._procs is not None
        self._procs.register(position_id, proc.pid)
        return proc.pid

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

    def close(self) -> None:
        if self._channel is not None:
            self._channel.close()
            self._channel = None
            self._stub = None
