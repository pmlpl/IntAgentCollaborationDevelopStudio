# cli/tui/widgets/page_shell.py — 全屏页面统一骨架（Header + 内容区 + Footer）
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.widgets import Footer, Header, Static


def compose_studio_page(
    *,
    title: str,
    subtitle: str = "",
    body_id: str = "page-body",
    shell_id: str = "page-shell",
    show_clock: bool = True,
) -> ComposeResult:
    """生成标准 Studio 全屏页：顶栏 / 标题 / 可滚动正文 / 底栏快捷键。"""
    yield Header(show_clock=show_clock)
    yield Container(
        Vertical(
            Static(f"[bold]{title}[/]", classes="title-text"),
            Static(subtitle, id="page-subtitle", classes="muted") if subtitle else Static("", id="page-subtitle", classes="muted"),
            id=body_id,
            classes="page-body",
        ),
        id=shell_id,
        classes="page-shell",
    )
    yield Footer()
