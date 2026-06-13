# tests/integration/test_tui_smoke.py — 轻量 smoke（完整挂载见 test_tui_screens.py）
def test_studio_app_importable():
    from cli.tui.app import StudioApp
    from cli.tui.screens.briefing import TaskDispatchScreen

    assert StudioApp.TITLE == "IntAgent Studio"
    assert TaskDispatchScreen is StudioApp.SCREENS["briefing"]


def test_run_studio_app_module():
    from cli.tui import app as app_mod

    assert hasattr(app_mod, "run_studio_app")


def test_tui_screen_modules_expose_compose():
    """各 Screen 至少能 import 且继承 Textual Screen。"""
    from textual.screen import Screen

    from cli.tui.screens.briefing import TaskDispatchScreen
    from cli.tui.screens.expand import ExpandScreen
    from cli.tui.screens.onboarding import OnboardingScreen
    from cli.tui.screens.project_hub import ProjectHubScreen

    for cls in (TaskDispatchScreen, OnboardingScreen, ExpandScreen, ProjectHubScreen):
        assert issubclass(cls, Screen)
        assert callable(getattr(cls, "compose", None))
