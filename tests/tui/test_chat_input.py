"""Tests for ChatInput widget: slash parsing, completion, history."""
from __future__ import annotations

import pytest

from cli.tui.widgets.chat_input import (
    ChatInput,
    SlashCommand,
    parse_slash_command,
    get_completions,
)


class TestParseSlashCommand:
    def test_slash_task(self):
        cmd = parse_slash_command("/task Add search feature")
        assert cmd is not None
        assert cmd.name == "task"
        assert cmd.args == "Add search feature"

    def test_slash_status_no_args(self):
        cmd = parse_slash_command("/status")
        assert cmd is not None
        assert cmd.name == "status"
        assert cmd.args == ""

    def test_slash_history_with_number(self):
        cmd = parse_slash_command("/history 50")
        assert cmd is not None
        assert cmd.name == "history"
        assert cmd.args == "50"

    def test_not_a_slash_command(self):
        cmd = parse_slash_command("hello world")
        assert cmd is None

    def test_slash_only(self):
        cmd = parse_slash_command("/")
        assert cmd is None


class TestGetCompletions:
    def test_slash_ta_completes_to_task(self):
        results = get_completions("/ta")
        assert "/task" in results

    def test_slash_st_completes_to_status(self):
        results = get_completions("/st")
        assert "/status" in results

    def test_at_man_completes(self):
        results = get_completions("@man", agent_ids=["manager-1", "worker-1"])
        assert "@manager-1" in results

    def test_empty_input_no_completions(self):
        results = get_completions("")
        assert results == []

    def test_unknown_slash_no_completions(self):
        results = get_completions("/zzz")
        assert results == []
