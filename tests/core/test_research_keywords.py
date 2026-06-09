from core.research.research import research_project


def test_research_project_snake_offline(monkeypatch):
    monkeypatch.setenv("STUDIO_RESEARCH_OFFLINE", "1")
    monkeypatch.setenv("STUDIO_WEB_SEARCH", "0")
    r = research_project("贪吃蛇小游戏")
    assert r["recommended_template"]
    assert "summary" in r
    assert r["source"] in ("offline", "agent")
