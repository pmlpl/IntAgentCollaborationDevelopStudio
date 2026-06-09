from core.research.web_search import (
    QuerySearchResult,
    SearchHit,
    WebGatherResult,
    _parse_bing_html,
    _simplify_query_for_github,
)


def test_simplify_query_for_github():
    assert "Vue3" in _simplify_query_for_github("Vue3 FastAPI 记账应用 技术栈 开发方案")
    assert "FastAPI" in _simplify_query_for_github("Vue3 FastAPI 记账应用 技术栈 开发方案")


def test_parse_bing_html_extracts_results():
    html = """
    <li class="b_algo">
      <h2><a href="https://example.com/a">Vue3 教程</a></h2>
      <p>Vue3 与 FastAPI 全栈开发入门。</p>
    </li>
    <li class="b_algo">
      <h2><a href="https://example.com/b">FastAPI 文档</a></h2>
      <p>现代 Python Web API 框架。</p>
    </li>
    """
    hits, blocks, err = _parse_bing_html(html, 5)
    assert err == ""
    assert blocks == 2
    assert len(hits) == 2
    assert hits[0].title == "Vue3 教程"
    assert "FastAPI" in hits[0].snippet


def test_web_gather_status_failed():
    gather = WebGatherResult(
        hits=[],
        queries=[
            QuerySearchResult(query="q1", error="网络错误: timeout"),
            QuerySearchResult(query="q2", error="网络错误: timeout"),
        ],
        elapsed_ms=12000,
    )
    assert gather.status == "failed"
    assert "失败" in gather.status_label()
    assert gather.hit_count == 0


def test_web_gather_status_no_results():
    gather = WebGatherResult(
        hits=[],
        queries=[
            QuerySearchResult(query="q1", html_bytes=80000, parsed_blocks=5),
            QuerySearchResult(query="q2", html_bytes=80000, parsed_blocks=3),
        ],
        elapsed_ms=4000,
    )
    assert gather.status == "no_results"
    assert "0 条" in gather.status_label()
    assert "已请求" in gather.status_label()


def test_web_gather_status_ok():
    gather = WebGatherResult(
        hits=[SearchHit(title="Python", snippet="web framework", url="https://example.com")],
        queries=[QuerySearchResult(query="q1", hits=[SearchHit(title="Python", snippet="web")])],
    )
    assert gather.status == "ok"
    assert "联网 1 条" in gather.status_label()
