# tests/core/platform/test_vector_memory.py — 向量记忆模块单元测试
"""测试 vector_memory 模块（无需 ChromaDB 安装时可验证数据流和错误处理）。"""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestVectorMemoryAvailability:
    """测试向量记忆可用性检查。"""

    def test_is_vector_available_true(self):
        from core.platform.vector_memory import is_vector_available
        # ChromaDB is installed in this env
        result = is_vector_available()
        assert result is True


class TestHybridSearch:
    """测试混合搜索 RRF 融合逻辑。"""

    def test_hybrid_search_vector_only(self):
        """仅有向量结果时返回原结果（不崩溃）。"""
        from core.platform.vector_memory import hybrid_search

        with tempfile.TemporaryDirectory() as td:
            persist_dir = Path(td)
            # 无 ChromaDB 数据时会返回空列表（不抛异常）
            results = hybrid_search(persist_dir, "test_ns", "query", fts_results=None, limit=5)
            assert isinstance(results, list)
            assert len(results) == 0

    def test_hybrid_search_with_fts_fallback(self):
        """FTS 结果也能正常传入（不崩溃）。"""
        from core.platform.vector_memory import hybrid_search

        fts_results = [
            {"key": "k1", "text": "First result", "score": 0.9},
            {"key": "k2", "text": "Second result", "score": 0.7},
        ]
        with tempfile.TemporaryDirectory() as td:
            persist_dir = Path(td)
            results = hybrid_search(persist_dir, "test_ns", "query", fts_results=fts_results, limit=5)
            assert isinstance(results, list)

    def test_vector_upsert_handles_errors(self):
        """向量写入在 ChromaDB 不可写时不应崩溃。"""
        from core.platform.vector_memory import vector_upsert, VectorMemoryError
        import tempfile

        # 写入临时目录应正常工作（如果模型已缓存）
        # 如果模型未缓存，函数会抛出 VectorMemoryError
        d = Path(tempfile.mkdtemp())
        try:
            try:
                vector_upsert(d, "test_e", "k1", "test text for upsert")
                # 成功则验证数据可搜索
                results = __import__("core.platform.vector_memory", fromlist=["vector_search"]).vector_search(
                    d, "test_e", "test", limit=5
                )
                assert isinstance(results, list)
            except VectorMemoryError:
                # 模型未下载或其他问题 — 这是合理的降级行为
                pass
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)


class TestMcpGateway:
    """测试 MCP Gateway 数据结构和连接池（通过文件路径导入避开 platform 命名冲突）。"""

    @staticmethod
    def _import_module(name: str):
        import importlib.util
        import sys
        mod_name = f"mcp_{name}"
        if mod_name in sys.modules:
            return sys.modules[mod_name]
        from pathlib import Path
        base = Path(__file__).resolve().parents[3] / "platform" / "mcp" / "gateway"
        spec = importlib.util.spec_from_file_location(mod_name, str(base / f"{name}.py"))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
        return mod

    def test_import_process_manager(self):
        """测试 MCP process_manager 模块可正常导入。"""
        pm = self._import_module("process_manager")
        assert pm.McpServerHandle is not None
        assert pm.McpProcessError is not None

    def test_import_pool(self):
        """测试 MCP connection pool 模块可正常导入。"""
        # 确保 process_manager 已加载到 sys.modules
        self._import_module("process_manager")
        pool_mod = self._import_module("pool")
        assert pool_mod.McpConnectionPool is not None
        pool = pool_mod.McpConnectionPool()
        assert pool.connected_servers() == []

    def test_mcp_handle_state(self):
        """测试 McpServerHandle 数据结构。"""
        pm = self._import_module("process_manager")
        handle = pm.McpServerHandle(server_id="test", command="npx", args=["--version"])
        assert handle.server_id == "test"
        assert handle.alive is False
        assert handle.initialized is False


class TestAgentHealth:
    """测试 Agent 健康检查模块。"""

    def test_import_health_module(self):
        """测试 health 模块可正常导入。"""
        from agents.health import check_command_exists, AgentHealthReport
        assert check_command_exists is not None
        report = AgentHealthReport(agent_id="test")
        assert report.agent_id == "test"
        assert report.healthy is False  # no checks run

    def test_check_command_exists_python(self):
        """python 命令应该在 PATH 中。"""
        from agents.health import check_command_exists
        ok, path = check_command_exists("python")
        assert ok is True
        assert len(path) > 0
