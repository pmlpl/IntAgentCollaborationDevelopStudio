# core/platform/mcp_client.py — MCP 注册表、RBAC 与 Gateway 骨架
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from core.org.tree_ops import OrgTree
from core.rbac.permission import effective_mcp_use


class McpError(Exception):
    """MCP 中台异常。"""


def registry_path(root: Path) -> Path:
    return root / "platform" / "mcp" / "registry.yaml"


def gateway_config_path(root: Path) -> Path:
    return root / "platform" / "mcp" / "gateway" / "config.yaml"


def load_mcp_registry(root: Path) -> dict[str, dict[str, Any]]:
    """读取 MCP 注册表，返回 id → meta。"""
    path = registry_path(root)
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    items = data.get("servers") or []
    return {item["id"]: item for item in items if item.get("id")}


def list_mcp_servers(root: Path) -> list[dict[str, Any]]:
    """列出全部已注册 MCP。"""
    return sorted(load_mcp_registry(root).values(), key=lambda x: x.get("id", ""))


def load_gateway_config(root: Path) -> dict[str, Any]:
    path = gateway_config_path(root)
    if not path.exists():
        return {"enabled": False}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def resolve_mcp_for_position(
    root: Path,
    position: dict[str, Any],
    *,
    tree: OrgTree | None = None,
) -> list[str]:
    """按 RBAC + resume 解析可用 MCP id。"""
    registry = load_mcp_registry(root)
    registry_ids = set(registry)
    if tree is None:
        declared = (position.get("resume") or {}).get("mcp_servers") or []
        return [mid for mid in declared if mid in registry]
    allowed = effective_mcp_use(tree, position, registry_ids)
    declared = set((position.get("resume") or {}).get("mcp_servers") or [])
    if declared:
        allowed &= declared | collect_explicit_mcp(position)
    return sorted(allowed)


def collect_explicit_mcp(position: dict[str, Any]) -> set[str]:
    block = (position.get("permissions") or {}).get("mcp") or {}
    return {str(x) for x in (block.get("use") or [])}


def write_mcp_allowlist(
    runtime_dir: Path,
    mcp_ids: list[str],
    root: Path,
) -> Path:
    """写入 runtime/mcp.allowlist.yaml，Gateway 与 adapter 读取。"""
    runtime_dir.mkdir(parents=True, exist_ok=True)
    registry = load_mcp_registry(root)
    entries = []
    for mid in mcp_ids:
        meta = registry.get(mid, {})
        entries.append(
            {
                "id": mid,
                "name": meta.get("name", mid),
                "transport": meta.get("transport", "stdio"),
            }
        )
    payload = {"servers": entries, "gateway": load_gateway_config(root)}
    path = runtime_dir / "mcp.allowlist.yaml"
    path.write_text(yaml.dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def audit_log_path(project_dir: Path, position_id: str) -> Path:
    return project_dir / "agents" / position_id / "logs" / "mcp-audit.log"


def append_mcp_audit(
    project_dir: Path,
    position_id: str,
    mcp_id: str,
    tool: str,
    *,
    ok: bool,
    detail: str = "",
) -> None:
    """追加 MCP 调用审计行。"""
    path = audit_log_path(project_dir, position_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "position_id": position_id,
        "mcp_id": mcp_id,
        "tool": tool,
        "ok": ok,
        "detail": detail,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


class McpGateway:
    """MCP Gateway：校验 allowlist + 写审计 + 真实 stdio 连接池。

    当 platform.yaml 中 mcp.gateway_enabled=true 时，
    使用 platform/mcp/gateway/ 中的 Python 原生连接池管理 MCP 服务器；
    为 false 时返回 stub 响应（默认行为）。
    """

    def __init__(self, root: Path, project_dir: Path, position_id: str):
        self.root = root
        self.project_dir = project_dir
        self.position_id = position_id
        self._allowlist = self._load_allowlist()
        self._real_pool: Any = None  # McpConnectionPool (lazy init)

    def _load_allowlist(self) -> set[str]:
        path = (
            self.project_dir
            / "agents"
            / self.position_id
            / "runtime"
            / "mcp.allowlist.yaml"
        )
        if not path.exists():
            return set()
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return {s["id"] for s in (data.get("servers") or []) if s.get("id")}

    def _cfg(self) -> dict[str, Any]:
        return load_gateway_config(self.root)

    def _get_pool(self):
        """延迟获取全局连接池（仅在 gateway_enabled=true 时）。

        通过文件路径导入以避免 platform/ 目录与 Python 内置 platform 模块冲突。
        先加载 process_manager 依赖，再加载 pool 模块。
        """
        if self._real_pool is None:
            try:
                import importlib.util
                import sys

                gateway_dir = self.root / "platform" / "mcp" / "gateway"

                # 1. 先加载 process_manager（pool 的依赖）
                pm_path = gateway_dir / "process_manager.py"
                if pm_path.is_file():
                    pm_spec = importlib.util.spec_from_file_location(
                        "mcp_process_manager", str(pm_path)
                    )
                    if pm_spec and pm_spec.loader:
                        pm_mod = importlib.util.module_from_spec(pm_spec)
                        sys.modules["mcp_process_manager"] = pm_mod
                        sys.modules["platform.mcp.gateway.process_manager"] = pm_mod
                        pm_spec.loader.exec_module(pm_mod)

                # 2. 再加载 pool
                pool_path = gateway_dir / "pool.py"
                if not pool_path.is_file():
                    raise McpError(f"MCP Gateway pool 文件不存在: {pool_path}")

                pool_spec = importlib.util.spec_from_file_location(
                    "mcp_gateway_pool", str(pool_path)
                )
                if pool_spec is None or pool_spec.loader is None:
                    raise McpError("无法加载 MCP Gateway pool 模块")
                pool_mod = importlib.util.module_from_spec(pool_spec)
                sys.modules["mcp_gateway_pool"] = pool_mod
                pool_spec.loader.exec_module(pool_mod)

                get_global_pool = getattr(pool_mod, "get_global_pool")
                self._real_pool = get_global_pool()
            except (ImportError, OSError) as exc:
                raise McpError(f"MCP Gateway 不可用: {exc}") from exc
        return self._real_pool

    def connect(self, mcp_id: str) -> bool:
        """建立到 MCP 服务器的连接。

        gateway_enabled=true: 实际启动 stdio 子进程并完成 initialize 握手。
        gateway_enabled=false: 仅校验 allowlist（不启动进程）。
        """
        if mcp_id not in self._allowlist:
            return False
        registry = load_mcp_registry(self.root)
        if mcp_id not in registry:
            return False

        cfg = self._cfg()
        if cfg.get("enabled", False):
            meta = registry[mcp_id]
            try:
                pool = self._get_pool()
                pool.connect(
                    mcp_id,
                    meta.get("command", "npx"),
                    meta.get("args", []),
                )
                return True
            except Exception as exc:
                logger.error("MCP connect %s failed: %s", mcp_id, exc)
                return False
        else:
            # Stub 模式：仅记录连接
            return True

    def disconnect(self, mcp_id: str) -> None:
        cfg = self._cfg()
        if cfg.get("enabled", False) and self._real_pool is not None:
            self._real_pool.disconnect(mcp_id)

    def connected_servers(self) -> list[str]:
        cfg = self._cfg()
        if cfg.get("enabled", False) and self._real_pool is not None:
            return self._real_pool.connected_servers()
        return []

    def invoke(self, mcp_id: str, tool: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        """代理 MCP 工具调用。

        gateway_enabled=true: 真实转发到 MCP server 进程。
        gateway_enabled=false: 返回 stub 响应。
        """
        args = args or {}
        registry = load_mcp_registry(self.root)
        if mcp_id not in self._allowlist:
            append_mcp_audit(
                self.project_dir, self.position_id, mcp_id, tool,
                ok=False, detail="not in allowlist",
            )
            raise McpError(f"MCP {mcp_id!r} not allowed for {self.position_id}")
        if mcp_id not in registry:
            append_mcp_audit(
                self.project_dir, self.position_id, mcp_id, tool,
                ok=False, detail="not in registry",
            )
            raise McpError(f"unknown MCP: {mcp_id}")

        cfg = self._cfg()
        if not cfg.get("enabled", False):
            append_mcp_audit(
                self.project_dir, self.position_id, mcp_id, tool,
                ok=True, detail="gateway disabled, stub response",
            )
            return {
                "ok": True, "stub": True,
                "mcp_id": mcp_id, "tool": tool, "args": args,
                "message": "MCP Gateway 已禁用（platform.yaml mcp.gateway_enabled=false）",
            }

        # 真实调用
        try:
            pool = self._get_pool()
            # 确保已连接
            pool.connect(
                mcp_id,
                registry[mcp_id].get("command", "npx"),
                registry[mcp_id].get("args", []),
            )
            result = pool.invoke(mcp_id, tool, args)
            append_mcp_audit(
                self.project_dir, self.position_id, mcp_id, tool,
                ok=True, detail="real stdio call succeeded",
            )
            return {
                "ok": True, "stub": False,
                "mcp_id": mcp_id, "tool": tool, "args": args,
                "result": result,
            }
        except Exception as exc:
            append_mcp_audit(
                self.project_dir, self.position_id, mcp_id, tool,
                ok=False, detail=str(exc),
            )
            raise McpError(f"MCP call {mcp_id}/{tool} failed: {exc}") from exc
