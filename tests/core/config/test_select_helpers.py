# tests/core/config/test_select_helpers.py — Textual Select 辅助函数（含 8.x API 回归）
from __future__ import annotations

import pytest
from textual.widgets import Select
from textual.widgets._select import InvalidSelectValueError

from core.config.select_helpers import safe_select_value, ui_select_options


def test_ui_select_options_swaps_to_label_value_pairs():
    opts = ui_select_options([("web-fullstack", "Web 全栈"), ("minimal", "精小团队")])
    assert opts == [("Web 全栈", "web-fullstack"), ("精小团队", "minimal")]


def test_safe_select_value_sets_legal_option_textual8():
    """Textual 8.x 用 _legal_values，无 .options — 此测试回归该 API。"""
    select = Select([("Web 全栈", "web-fullstack"), ("精小团队", "minimal")])
    assert not hasattr(select, "options") or not callable(getattr(select, "options", None))

    safe_select_value(select, "web-fullstack", fallback="minimal")
    assert select.value == "web-fullstack"


def test_safe_select_value_fallback_when_unknown():
    select = Select([("A", "a"), ("B", "b")])
    safe_select_value(select, "missing-id", fallback="a")
    assert select.value == "a"


def test_safe_select_value_blank_for_none():
    select = Select([("A", "a")], allow_blank=True)
    safe_select_value(select, None)
    assert select.value is Select.NULL


def test_select_direct_assign_still_raises_for_unknown():
    select = Select([("A", "a")])
    with pytest.raises(InvalidSelectValueError):
        select.value = "opencode"
