from core.platform.memory_client import MemoryError, resolve_memory_namespace


def test_resolve_memory_namespace_shorthand():
    assert resolve_memory_namespace("project", "222") == "project/222"
    assert resolve_memory_namespace("project/", "222") == "project/222"


def test_resolve_memory_namespace_exact():
    assert resolve_memory_namespace("project/222", "222") == "project/222"
    assert resolve_memory_namespace("agent/laowang", "222") == "agent/laowang"


def test_resolve_memory_namespace_mismatch():
    try:
        resolve_memory_namespace("project/demo", "222")
        assert False, "should raise"
    except MemoryError as exc:
        assert "222" in str(exc)
        assert "project/222" in str(exc)
