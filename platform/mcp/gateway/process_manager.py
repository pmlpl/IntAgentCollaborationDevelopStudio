# platform/mcp/gateway/process_manager.py — MCP 服务器 stdio 子进程管理
#
# 负责：
# 1. 启动/停止 MCP server 进程（stdio 管道）
# 2. JSON-RPC 2.0 消息收发
# 3. initialize 握手 → tools/list → tools/call
# 4. 健康检查（进程存活 + ping）
# 5. 连接池复用（同类型 server 共享一个进程）
from __future__ import annotations

import json
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.logging import get_logger

logger = get_logger(__name__)

# MCP JSON-RPC 版本
MCP_PROTOCOL_VERSION = "2024-11-05"
# 启动 / 调用超时（秒）
INIT_TIMEOUT = 15
TOOL_TIMEOUT = 60
PING_TIMEOUT = 5


class McpProcessError(Exception):
    """MCP 进程操作异常。"""


@dataclass
class McpServerHandle:
    """MCP server 进程句柄。"""

    server_id: str
    command: str
    args: list[str] = field(default_factory=list)
    process: subprocess.Popen | None = None
    initialized: bool = False
    server_info: dict[str, Any] = field(default_factory=dict)
    tools: list[dict[str, Any]] = field(default_factory=list)
    started_at: float = 0.0
    last_used: float = 0.0
    error: str = ""

    @property
    def alive(self) -> bool:
        if self.process is None:
            return False
        return self.process.poll() is None

    def ensure_alive(self) -> None:
        if not self.alive:
            rc = self.process.returncode if self.process else -1
            raise McpProcessError(
                f"MCP server {self.server_id!r} 进程已退出 (rc={rc})"
                + (f": {self.error}" if self.error else "")
            )


def _build_argv(command: str, args: list[str]) -> list[str]:
    """构建 subprocess 可用的 argv 列表。"""
    import shutil
    resolved = shutil.which(command) or command
    return [resolved, *args]


def _send_jsonrpc(proc: subprocess.Popen, request: dict[str, Any]) -> None:
    """通过 stdin 发送 JSON-RPC 请求。"""
    if proc.stdin is None or proc.poll() is not None:
        raise McpProcessError("MCP server stdin 不可写（进程可能已退出）")
    payload = json.dumps(request, ensure_ascii=False) + "\n"
    proc.stdin.write(payload)
    proc.stdin.flush()


def _recv_jsonrpc(proc: subprocess.Popen, timeout: float) -> Any:
    """从 stdout 读取一行 JSON-RPC 响应（带超时）。"""
    import select
    if proc.stdout is None:
        raise McpProcessError("MCP server stdout 不可读")

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        ready, _, _ = select.select([proc.stdout], [], [], min(remaining, 1.0))
        if not ready:
            continue
        line = proc.stdout.readline()
        if not line:
            # EOF — 进程可能已退出
            rc = proc.poll()
            raise McpProcessError(
                f"MCP server stdout closed unexpectedly (rc={rc})"
            )
        line = line.strip()
        if not line:
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError as exc:
            logger.warning("MCP non-JSON line from %s: %.200s", proc.args, line)
            continue

    raise McpProcessError(f"MCP server 响应超时（>{timeout}s）")


def _rpc_call(
    proc: subprocess.Popen,
    method: str,
    params: dict[str, Any] | None = None,
    timeout: float = TOOL_TIMEOUT,
) -> dict[str, Any]:
    """发送 JSON-RPC 请求并解析响应。"""
    req_id = str(uuid.uuid4())[:8]
    request = {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": method,
        "params": params or {},
    }
    _send_jsonrpc(proc, request)
    response = _recv_jsonrpc(proc, timeout)

    if not isinstance(response, dict):
        raise McpProcessError(f"非法 JSON-RPC 响应类型: {type(response).__name__}")

    if "error" in response:
        err = response["error"]
        raise McpProcessError(
            f"JSON-RPC error: {err.get('message', str(err))}"
            f" (code={err.get('code', -1)})"
        )

    if "result" not in response:
        raise McpProcessError(f"JSON-RPC 响应缺少 result: {list(response.keys())}")

    return response["result"]


def start_server(
    server_id: str,
    command: str,
    args: list[str],
    *,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> McpServerHandle:
    """启动 MCP server 子进程并完成 initialize 握手。"""
    argv = _build_argv(command, args)
    logger.info("MCP start: %s cmd=%s args=%s", server_id, command, args)

    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            cwd=cwd,
        )
    except (FileNotFoundError, OSError) as exc:
        raise McpProcessError(f"无法启动 MCP server {server_id!r}: {exc}") from exc

    handle = McpServerHandle(
        server_id=server_id,
        command=command,
        args=list(args),
        process=proc,
        started_at=time.monotonic(),
        last_used=time.monotonic(),
    )

    # initialize 握手
    try:
        init_result = _rpc_call(
            proc,
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {
                    "name": "Studio-MCP-Gateway",
                    "version": "0.2.0",
                },
            },
            timeout=INIT_TIMEOUT,
        )
        handle.server_info = init_result
        handle.initialized = True
        logger.info(
            "MCP %s initialized: name=%s version=%s",
            server_id,
            init_result.get("serverInfo", {}).get("name", server_id),
            init_result.get("protocolVersion", "unknown"),
        )

        # 发送 initialized 通知（MCP 协议要求）
        _send_jsonrpc(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})

        # 获取工具列表
        tools_result = _rpc_call(proc, "tools/list", timeout=TOOL_TIMEOUT)
        handle.tools = tools_result.get("tools", [])
        logger.info("MCP %s tools: %d", server_id, len(handle.tools))

    except McpProcessError:
        # 握手失败，尝试清理
        stop_server(handle)
        raise

    return handle


def stop_server(handle: McpServerHandle) -> None:
    """优雅关闭 MCP server 进程。"""
    if handle.process is None:
        return
    try:
        if handle.process.poll() is None:
            # 尝试优雅关闭
            try:
                _send_jsonrpc(handle.process, {
                    "jsonrpc": "2.0",
                    "method": "shutdown",
                    "id": str(uuid.uuid4())[:8],
                })
                handle.process.wait(timeout=3)
            except Exception:
                pass
        if handle.process.poll() is None:
            handle.process.terminate()
            try:
                handle.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                handle.process.kill()
                handle.process.wait(timeout=2)
    except Exception as exc:
        logger.warning("MCP stop %s: cleanup error: %s", handle.server_id, exc)
    finally:
        handle.initialized = False
        handle.process = None


def call_tool(handle: McpServerHandle, tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """调用 MCP 工具并返回结果。"""
    handle.ensure_alive()
    handle.last_used = time.monotonic()
    params: dict[str, Any] = {"name": tool_name}
    if arguments:
        params["arguments"] = arguments
    return _rpc_call(handle.process, "tools/call", params, timeout=TOOL_TIMEOUT)


def ping_server(handle: McpServerHandle) -> bool:
    """发送 ping 检查服务器是否响应。"""
    if not handle.alive:
        return False
    try:
        result = _rpc_call(handle.process, "ping", timeout=PING_TIMEOUT)
        return True
    except McpProcessError:
        return False


def list_tools(handle: McpServerHandle) -> list[dict[str, Any]]:
    """获取服务器工具列表（刷新缓存）。"""
    handle.ensure_alive()
    result = _rpc_call(handle.process, "tools/list", timeout=TOOL_TIMEOUT)
    handle.tools = result.get("tools", [])
    return handle.tools
