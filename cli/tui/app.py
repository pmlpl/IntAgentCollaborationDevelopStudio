# cli/tui/app.py — Textual 应用入口
from __future__ import annotations

from textual.app import App

from cli.tui.screens.agent_list import AgentListScreen
from cli.tui.screens.chat import ChatScreen
from cli.tui.screens.briefing import TaskDispatchScreen
from cli.tui.screens.dashboard import DashboardScreen
from cli.tui.screens.onboarding import OnboardingScreen
from cli.tui.screens.project_hub import ProjectHubScreen
from cli.tui.screens.review import ReviewScreen
from cli.tui.screens.welcome import WelcomeScreen
from core.project import get_studio_root, list_registered_projects, resolve_project_id, set_current_project


class StudioApp(App):
    """IntAgent Studio 指挥舱。"""

    CSS_PATH = "theme.tcss"
    TITLE = "IntAgent Studio"
    SUB_TITLE = "CEO 控制台"

    SCREENS = {
        "welcome": WelcomeScreen,
        "project_hub": ProjectHubScreen,
        "onboarding": OnboardingScreen,
        "briefing": TaskDispatchScreen,
        "dashboard": DashboardScreen,
        "review": ReviewScreen,
        "agent_list": AgentListScreen,
        "chat": ChatScreen,
    }

    def __init__(self) -> None:
        super().__init__()
        self.project_name: str | None = None
        self.pending_orchestration: str | None = None
        self.auto_open_task_dispatch: bool = False

    def on_mount(self) -> None:
        root = get_studio_root()
        projects = list_registered_projects(root)
        if not projects:
            self.push_screen("welcome")
            return
        try:
            project_id = resolve_project_id(root)
            set_current_project(root, project_id)
            self.project_name = project_id
            self.push_screen("dashboard")
        except FileNotFoundError:
            self.push_screen("project_hub")


def run_studio_app() -> int:
    """启动 Textual 指挥舱。"""
    app = StudioApp()
    app.run()
    return 0
