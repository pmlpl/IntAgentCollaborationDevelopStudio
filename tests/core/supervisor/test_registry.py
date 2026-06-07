from pathlib import Path

from core.supervisor.registry import PortRegistry


def test_port_acquire_release(tmp_path: Path):
    reg = PortRegistry(tmp_path / "ports.json", 41000, 41010)
    port = reg.acquire("agent-a")
    assert 41000 <= port <= 41010
    reg.release(port)
    port2 = reg.acquire("agent-b")
    assert port2 != 0
