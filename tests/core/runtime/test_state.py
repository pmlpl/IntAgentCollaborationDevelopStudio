from pathlib import Path

from core.runtime.state import AgentRuntimeState, read_state, write_state


def test_write_and_read_state(tmp_path: Path):
    agent_dir = tmp_path / "agents" / "xiaohong"
    write_state(agent_dir, AgentRuntimeState(task_id="t1", status="working", progress=50, message="ok"))
    state = read_state(agent_dir)
    assert state.task_id == "t1"
    assert state.progress == 50
