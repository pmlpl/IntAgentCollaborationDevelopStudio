# core/workspace/worktree.py — Git Worktree 管理
from __future__ import annotations

import subprocess
from pathlib import Path

from core.logging import get_logger

logger = get_logger(__name__)


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
        """创建 worktree 并返回路径。分支名加随机后缀避免冲突。"""
        import uuid

        suffix = uuid.uuid4().hex[:6]
        branch = f"studio/{task_id}-{slug}-{suffix}"
        dest = self.workspaces_root / f"{task_id}-{slug}"
        if dest.exists():
            # 已存在则复用，不创建新 worktree
            logger.info("worktree: reuse existing %s", dest)
            return dest
        logger.info("worktree: create branch=%s dest=%s", branch, dest)
        self._run("branch", branch, "HEAD")
        self._run("worktree", "add", str(dest), branch)
        return dest

    def remove(self, worktree_name: str) -> None:
        dest = self.workspaces_root / worktree_name
        if not dest.exists():
            raise WorktreeError(f"worktree not found: {dest}")
        logger.info("worktree: remove %s", dest)
        self._run("worktree", "remove", str(dest), "--force")
        branch_name = f"studio/{worktree_name}"
        subprocess.run(
            ["git", "branch", "-D", branch_name],
            cwd=self.repo_path,
            capture_output=True,
        )

    # ── merge ──

    def merge(self, worktree_name: str) -> dict[str, object]:
        """将 worktree 分支合并回当前分支。

        返回 {"merged": True, "branch": str} 成功，或
        {"merged": False, "conflicts": [...], "branch": str} 冲突。
        """
        branch = f"studio/{worktree_name}"
        result: dict[str, object] = {"branch": branch}

        # 先 checkout 回原分支
        try:
            self._run("checkout", branch)
            self._run("checkout", "-")
        except subprocess.CalledProcessError as exc:
            logger.error("merge: checkout failed: %s", exc.stderr)
            result["merged"] = False
            result["conflicts"] = [f"checkout error: {exc.stderr.strip()}"]
            return result

        # 尝试合并
        try:
            self._run("merge", "--no-ff", branch, "-m", f"Studio merge: {worktree_name}")
            logger.info("merge: %s merged OK", branch)
            result["merged"] = True
            # 清理分支和 worktree
            try:
                self.remove(worktree_name)
            except WorktreeError:
                pass
        except subprocess.CalledProcessError as exc:
            conflicts = _parse_conflict_files(exc.stderr or exc.stdout or "")
            logger.warning("merge: %s conflict, files=%s", branch, conflicts)
            result["merged"] = False
            result["conflicts"] = conflicts
            # 中止合并，保留分支供人工处理
            subprocess.run(
                ["git", "merge", "--abort"],
                cwd=self.repo_path,
                capture_output=True,
            )

        return result


def _parse_conflict_files(git_output: str) -> list[str]:
    """从 git merge 冲突输出中解析冲突文件列表。"""
    conflicts: list[str] = []
    for line in git_output.splitlines():
        line = line.strip()
        if line.startswith("CONFLICT") and ":" in line:
            # 提取文件名
            parts = line.split("in ", 1)
            if len(parts) > 1:
                conflicts.append(parts[1].strip().rstrip("."))
    return conflicts if conflicts else ["unknown"]
