from unittest.mock import patch

from core.research.agent_research import (
    RESEARCH_MARKER,
    ResearchReport,
    _offline_synthesize,
    format_report_for_ui,
    parse_research_output,
    report_to_result_dict,
    run_agent_research,
)
from core.research.web_search import SearchHit, WebGatherResult, QuerySearchResult


def test_parse_research_output():
    raw = f"分析\n{RESEARCH_MARKER}\n" + '{"technologies":["Python","Pygame"],"similar_products":[{"name":"snake","note":"classic"}],"similar_local_template":null,"recommended_template":"minimal","summary":"适合小团队"}'
    data = parse_research_output(raw)
    assert "Python" in data["technologies"]
    assert data["recommended_template"] == "minimal"


def test_offline_synthesize_snake_game():
    hits = [
        SearchHit(title="Snake game JavaScript Canvas", snippet="HTML5 canvas snake tutorial"),
        SearchHit(title="Python pygame snake", snippet="pygame snake game example"),
    ]
    report = _offline_synthesize("贪吃蛇小游戏", hits, None)
    assert report.recommended_template in ("minimal", "web-fullstack", "multi-endpoint")
    assert report.similar_products
    assert "离线" in report.summary or report.source == "offline"


def test_format_report_shows_technologies():
    report = ResearchReport(
        description="贪吃蛇小游戏",
        technologies=["JavaScript", "Canvas"],
        similar_products=[{"name": "经典贪吃蛇", "note": "Canvas 实现"}],
        recommended_template="minimal",
        summary="适合精小团队快速交付",
        source="agent",
    )
    text = format_report_for_ui(report)
    assert "JavaScript" in text
    assert "经典贪吃蛇" in text


@patch("core.research.agent_research.gather_web_research")
@patch("core.research.agent_research.agent_available", return_value=False)
def test_run_agent_research_offline_when_no_agent(_avail, mock_gather):
    mock_gather.return_value = WebGatherResult(
        hits=[SearchHit(title="Snake HTML5", snippet="build snake with canvas")],
        queries=[],
        elapsed_ms=100.0,
    )
    report = run_agent_research("贪吃蛇小游戏", force_offline=True)
    result = report_to_result_dict(report)
    assert result["source"] == "offline"
    assert "summary" in result
