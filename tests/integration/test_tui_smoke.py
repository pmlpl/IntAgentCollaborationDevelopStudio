def test_studio_app_importable():
    from cli.tui.app import StudioApp
    from cli.tui.screens.briefing import TaskDispatchScreen

    assert StudioApp.TITLE == "IntAgent Studio"
    assert TaskDispatchScreen is StudioApp.SCREENS["briefing"]


def test_run_studio_app_module():
    from cli.tui import app as app_mod

    assert hasattr(app_mod, "run_studio_app")
