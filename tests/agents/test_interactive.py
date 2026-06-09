from pathlib import Path

import yaml

from agents.interactive import STUDIO_TASK_REL, build_interactive_argv, write_task_context_file


def test_write_task_context_file(tmp_path: Path):
    worktree = tmp_path / "wt"
    worktree.mkdir()
    rel = write_task_context_file(worktree, "实现登录页")
    assert rel == Path(STUDIO_TASK_REL)
    assert (worktree / STUDIO_TASK_REL).read_text(encoding="utf-8") == "实现登录页"


def test_build_interactive_argv_claude(tmp_path: Path):
    cfg = {
        "command": "claude",
        "flags_interactive": "",
        "interactive": {"mode": "append_system_prompt_file"},
    }
    argv = build_interactive_argv(cfg, task_file_rel=Path(STUDIO_TASK_REL))
    assert "-p" not in argv
    assert "--append-system-prompt-file" in argv


def test_build_interactive_argv_opencode_run_interactive(tmp_path: Path):
    cfg = {
        "command": "opencode",
        "flags_interactive": "",
        "interactive": {"mode": "run_interactive"},
    }
    worktree = tmp_path / "wt"
    worktree.mkdir()
    write_task_context_file(worktree, "CEO 任务正文")
    argv = build_interactive_argv(
        cfg, task_file_rel=Path(STUDIO_TASK_REL), worktree=worktree
    )
    assert "run" in argv
    assert "-i" in argv
    assert "-f" not in argv
    assert "CEO 任务正文" in argv[-1]


def test_build_interactive_argv_hermes_tui():
    cfg = {
        "command": "hermes",
        "flags_interactive": "chat --tui",
        "interactive": {"mode": "task_file_context"},
    }
    argv = build_interactive_argv(cfg, task_file_rel=Path(STUDIO_TASK_REL))
    joined = " ".join(argv)
    assert "chat" in joined
    assert "--tui" in joined
    assert "-z" not in argv


def test_write_hermes_context_file(tmp_path: Path):
    from agents.interactive import (
        HERMES_CONTEXT_REL,
        prepare_hermes_worker_context,
        write_hermes_context_file,
    )

    worktree = tmp_path / "wt"
    worktree.mkdir()
    write_hermes_context_file(worktree, "后端任务说明")
    assert (worktree / HERMES_CONTEXT_REL).read_text(encoding="utf-8") == "后端任务说明"

    env = prepare_hermes_worker_context(
        worktree, "完整任务正文", task_id="task-abc"
    )
    assert "HERMES_TUI_QUERY" in env
    assert "task-abc" in env["HERMES_TUI_QUERY"]
    assert (worktree / "AGENTS.md").read_text(encoding="utf-8") == "完整任务正文"
