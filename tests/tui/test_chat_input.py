"""Tests for ChatInput widget: slash parsing, completion, filter_commands."""
from __future__ import annotations

import pytest

from cli.tui.widgets.chat_input import (
    ChatInputArea,
    CompletionDropdown,
    SlashCommand,
    parse_slash_command,
    get_completions,
    filter_commands,
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


class TestFilterCommands:
    def test_empty_prefix_returns_all(self):
        results = filter_commands("")
        assert len(results) == 9
        names = [r[0] for r in results]
        assert "task" in names
        assert "help" in names
        assert "model" in names

    def test_ta_matches_task(self):
        results = filter_commands("ta")
        assert len(results) == 1
        assert results[0][0] == "task"

    def test_s_matches_status(self):
        results = filter_commands("s")
        names = [r[0] for r in results]
        assert "status" in names

    def test_st_matches_status(self):
        results = filter_commands("st")
        assert len(results) == 1
        assert results[0][0] == "status"

    def test_zzz_matches_nothing(self):
        results = filter_commands("zzz")
        assert results == []

    def test_returns_name_and_description(self):
        results = filter_commands("help")
        assert results[0] == ("help", "显示所有命令帮助")
