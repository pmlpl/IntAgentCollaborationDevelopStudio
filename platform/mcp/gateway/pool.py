# platform/mcp/gateway/pool.py — MCP 服务器连接池
#
# 同类型 MCP server 共享一个 stdio 进程；
# 健康检查自动回收死进程；
# 请求路由到正确的 server 进程。
#
# 注意：此模块通过 importlib 文件路径加载（避免 platform/ 与 stdlib 冲突），
# 因此使用 _import_process_manager() 而非常规 import。
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

from core.logging import get_logger


def _import_process_manager():
    """导入 process_manager 模块（处理 platform/ 命名冲突）。"""
    # 尝试从 sys.modules 中获取（由 mcp_client._get_pool 预加载）
    for name in ("mcp_process_manager", "platform.mcp.gateway.process_manager"):
        mod = sys.modules.get(name)
        if mod is not None:
            return mod

    # 回退：通过文件路径加载
    import importlib.util

    pm_path = Path(__file__).resolve().parent / "process_manager.py"
    spec = importlib.util.spec_from_file_location("mcp_process_manager", str(pm_path))
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 MCP process_manager: {pm_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["mcp_process_manager"] = mod
    sys.modules["platform.mcp.gateway.process_manager"] = mod
    spec.loader.exec_module(mod)
    return mod


_pm = _import_process_manager()
McpProcessError = _pm.McpProcessError
McpServerHandle = _pm.McpServerHandle
call_tool = _pm.call_tool
list_tools = _pm.list_tools
ping_server = _pm.ping_server
start_server = _pm.start_server
stop_server = _pm.stop_server

logger = get_logger(__name__)


class McpConnectionPool:
    """MCP 服务器连接池。

    用法:
        pool = McpConnectionPool()
        pool.connect("postgres-mcp", "npx", ["-y", "@modelcontextprotocol/server-postgres", "..."])
        result = pool.invoke("postgres-mcp", "query", {"sql": "SELECT 1"})
    """

    def __init__(self):
        self._handles: dict[str, McpServerHandle] = {}
        self._last_health_check: float = 0.0

    # ── 连接管理 ──

    def connect(
        self,
        server_id: str,
        command: str,
        args: list[str],
        *,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
    ) -> McpServerHandle:
        """建立连接或返回已有连接。"""
        existing = self._handles.get(server_id)
        if existing is not None and existing.alive:
            logger.debug("MCP pool: reuse %s", server_id)
            existing.last_used = time.monotonic()
            return existing

        # 清理死连接
        if existing is not None:
            logger.info("MCP pool: replacing dead connection for %s", server_id)
            try:
                stop_server(existing)
            except Exception:
                pass

        handle = start_server(server_id, command, args, env=env, cwd=cwd)
        self._handles[server_id] = handle
        return handle

    def disconnect(self, server_id: str) -> None:
        """断开并移除连接。"""
        handle = self._handles.pop(server_id, None)
        if handle is not None:
            stop_server(handle)

    def shutdown(self) -> None:
        """关闭所有连接。"""
        for sid in list(self._handles):
            self.disconnect(sid)

    # ── 工具调用 ──

    def invoke(
        self,
        server_id: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """调用 MCP 工具。自动重连一次。"""
        handle = self._handles.get(server_id)
        if handle is None:
            raise McpProcessError(f"MCP server {server_id!r} 未连接")

        try:
            return call_tool(handle, tool_name, arguments)
        except McpProcessError:
            # 尝试重连后重试一次
            logger.warning("MCP pool: %s call failed, attempting reconnect", server_id)
            try:
                handle = self._reconnect(server_id)
                return call_tool(handle, tool_name, arguments)
            except McpProcessError:
                raise

    def list_tools(self, server_id: str) -> list[dict[str, Any]]:
        """获取 server 工具列表。"""
        handle = self._handles.get(server_id)
        if handle is None:
            raise McpProcessError(f"MCP server {server_id!r} 未连接")
        return list_tools(handle)

    def connected_servers(self) -> list[str]:
        """返回已连接的 server ID 列表。"""
        return [sid for sid, h in self._handles.items() if h.alive]

    def server_info(self, server_id: str) -> dict[str, Any]:
        """返回 server 信息。"""
        handle = self._handles.get(server_id)
        if handle is None:
            return {}
        return {
            "server_id": server_id,
            "command": handle.command,
            "alive": handle.alive,
            "initialized": handle.initialized,
            "tool_count": len(handle.tools),
            "server_info": handle.server_info,
            "error": handle.error,
        }

    # ── 健康检查 ──

    def health_check(self) -> dict[str, bool]:
        """对所有连接执行 ping 检查，自动回收死连接。"""
        self._last_health_check = time.monotonic()
        results: dict[str, bool] = {}
        for sid in list(self._handles):
            handle = self._handles[sid]
            if not handle.alive:
                results[sid] = False
                self._handles.pop(sid, None)
                continue
            ok = ping_server(handle)
            results[sid] = ok
            if not ok:
                logger.warning("MCP pool: %s health check failed, removing", sid)
                self.disconnect(sid)
        return results

    def health_check_needed(self, staleness_sec: float = 30.0) -> bool:
        """是否需要执行健康检查。"""
        return (time.monotonic() - self._last_health_check) > staleness_sec

    # ── 内部 ──

    def _reconnect(self, server_id: str) -> McpServerHandle:
        """重新连接指定 server。"""
        old = self._handles.pop(server_id, None)
        if old is not None:
            try:
                stop_server(old)
            except Exception:
                pass
        # 用旧连接的命令/参数重建
        if old is None:
            raise McpProcessError(f"无法重连 {server_id!r}：无历史连接信息")
        return self.connect(server_id, old.command, old.args)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.shutdown()
        return False


# ── 全局池单例 ──

_global_pool: McpConnectionPool | None = None


def get_global_pool() -> McpConnectionPool:
    """获取全局 MCP 连接池单例。"""
    global _global_pool
    if _global_pool is None:
        _global_pool = McpConnectionPool()
    return _global_pool


def shutdown_global_pool() -> None:
    """关闭全局连接池。"""
    global _global_pool
    if _global_pool is not None:
        _global_pool.shutdown()
        _global_pool = None
