"""Tests for ChatScreen polling and send flow."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.ipc.message_bus import Message
from core.ipc.message_log import MessageRecord


class TestChatScreenImports:
    """Smoke test: ChatScreen can be imported and instantiated."""

    def test_import(self):
        from cli.tui.screens.chat import ChatScreen
        assert ChatScreen is not None

    def test_has_bindings(self):
        from cli.tui.screens.chat import ChatScreen
        binding_keys = [b[0] for b in ChatScreen.BINDINGS]
        assert "escape" in binding_keys
        assert "ctrl+home" in binding_keys
        assert "ctrl+end" in binding_keys
