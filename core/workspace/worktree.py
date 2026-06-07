# core/workspace/worktree.py — Git Worktree 管理
from __future__ import annotations

import subprocess
from pathlib import Path


class WorktreeError(Exception):
    """Worktree 操作异常。"""


class WorktreeManager:
    """为每个任务创建独立 Git Worktree。"""

    def __init__(self, repo_path: Path, workspaces_root: Path):
        self.repo_path = repo_path.resolve()
        self.workspaces_root = workspaces_root.resolve()
        self.workspaces_root.mkdir(parents=True, exist_ok=True)

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=self.repo_path,
            check=True,
            capture_output=True,
            text=True,
        )

    def create(self, task_id: str, slug: str) -> Path:
        branch = f"studio/{task_id}-{slug}"
        dest = self.workspaces_root / f"{task_id}-{slug}"
        if dest.exists():
            raise WorktreeError(f"worktree already exists: {dest}")
        self._run("branch", branch, "HEAD")
        self._run("worktree", "add", str(dest), branch)
        return dest

    def remove(self, worktree_name: str) -> None:
        dest = self.workspaces_root / worktree_name
        if not dest.exists():
            raise WorktreeError(f"worktree not found: {dest}")
        self._run("worktree", "remove", str(dest), "--force")
        branch_name = f"studio/{worktree_name}"
        subprocess.run(
            ["git", "branch", "-D", branch_name],
            cwd=self.repo_path,
            capture_output=True,
        )
