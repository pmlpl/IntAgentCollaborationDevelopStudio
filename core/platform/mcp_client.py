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
    """MCP Gateway 骨架：校验 allowlist + 写审计，暂不真正拉起 stdio 进程。"""

    def __init__(self, root: Path, project_dir: Path, position_id: str):
        self.root = root
        self.project_dir = project_dir
        self.position_id = position_id
        self._allowlist = self._load_allowlist()

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

    def invoke(self, mcp_id: str, tool: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        """代理 MCP 工具调用（Phase 2 骨架返回 stub）。"""
        args = args or {}
        registry = load_mcp_registry(self.root)
        if mcp_id not in self._allowlist:
            append_mcp_audit(
                self.project_dir,
                self.position_id,
                mcp_id,
                tool,
                ok=False,
                detail="not in allowlist",
            )
            raise McpError(f"MCP {mcp_id!r} not allowed for {self.position_id}")
        if mcp_id not in registry:
            append_mcp_audit(
                self.project_dir,
                self.position_id,
                mcp_id,
                tool,
                ok=False,
                detail="not in registry",
            )
            raise McpError(f"unknown MCP: {mcp_id}")
        append_mcp_audit(
            self.project_dir,
            self.position_id,
            mcp_id,
            tool,
            ok=True,
            detail="gateway stub",
        )
        return {
            "ok": True,
            "stub": True,
            "mcp_id": mcp_id,
            "tool": tool,
            "args": args,
            "message": "MCP Gateway 骨架：尚未连接真实 stdio 进程",
        }
