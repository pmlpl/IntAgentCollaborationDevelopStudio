# core/config/select_helpers.py — Textual Select 选项与设值辅助
from __future__ import annotations

from textual.widgets import Select
from textual.widgets._select import InvalidSelectValueError


def ui_select_options(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """(value, 显示名) → Textual Select 需要的 (显示名, value)。"""
    return [(label, value) for value, label in pairs]


def _legal_select_values(widget: Select) -> set[str]:
    """Textual 8.x：合法值在 _legal_values，无 .options 属性。"""
    legal = getattr(widget, "_legal_values", None)
    if legal is None:
        return set()
    blank = Select.NULL
    return {str(v) for v in legal if v is not blank and v is not Select.BLANK}


def safe_select_value(
    widget: Select,
    value: str | None,
    *,
    fallback: str | object | None = Select.BLANK,
) -> None:
    """仅在 value 存在于当前选项时赋值，避免 InvalidSelectValueError。"""
    blank = Select.NULL
    if value is None or value is blank or value is Select.BLANK:
        widget.value = blank
        return

    text = str(value)
    legal = _legal_select_values(widget)
    if legal and text not in legal:
        if fallback is not None and fallback is not blank and fallback is not Select.BLANK:
            widget.value = fallback  # type: ignore[assignment]
        else:
            widget.value = blank
        return

    try:
        widget.value = text  # type: ignore[assignment]
    except InvalidSelectValueError:
        if fallback is not None and fallback is not blank and fallback is not Select.BLANK:
            widget.value = fallback  # type: ignore[assignment]
        else:
            widget.value = blank
