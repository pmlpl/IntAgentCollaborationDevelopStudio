import subprocess
from pathlib import Path

from core.workspace.worktree import WorktreeManager


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_create_and_remove_worktree(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@test.com")
    _git(repo, "config", "user.name", "test")
    (repo / "README.md").write_text("# test", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init")

    ws_root = tmp_path / "workspaces"
    mgr = WorktreeManager(repo, ws_root)
    path = mgr.create("task-001", "search-ui")
    assert path.is_dir()
    assert (path / "README.md").exists()
    mgr.remove("task-001-search-ui")
    assert not path.exists()
