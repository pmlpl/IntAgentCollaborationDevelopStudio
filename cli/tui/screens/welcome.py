# cli/tui/screens/welcome.py
from __future__ import annotations

from cli.tui.screens.onboarding import OnboardingScreen
from textual.app import ComposeResult
from textual.containers import Container, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Static


class WelcomeScreen(Screen):
    """欢迎屏（无任何项目时）。"""

    BINDINGS = [
        ("enter", "start", "新建项目"),
        ("n", "start", "新建项目"),
        ("a", "agents", "Agent 目录"),
        ("q", "quit", "退出"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Container(
            VerticalScroll(
                Static(
                    "\n\n  IntAgent Studio\n  多 Agent 协作开发管理平台\n\n"
                    "  你是 CEO。为每个项目选一个文件夹，\n"
                    "  开公司、派任务、看进度。\n"
                    "  Agent 在独立终端窗口中工作。",
                    id="welcome-text",
                    classes="title-text",
                ),
                id="welcome-box",
                classes="panel-box",
            ),
            id="welcome-container",
        )
        yield Footer()

    def action_agents(self) -> None:
        self.app.push_screen("agent_list")

    def action_start(self) -> None:
        self.app.push_screen(OnboardingScreen())

    def action_quit(self) -> None:
        self.app.exit()
