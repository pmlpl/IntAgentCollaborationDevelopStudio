# core/research/web_search.py — 联网搜索（Bing / DuckDuckGo，自动回退）
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from html import unescape
from pathlib import Path
from typing import Callable

import yaml

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_TIMEOUT = 15
_DEFAULT_PROVIDERS = ("github", "bing", "duckduckgo")


@dataclass
class SearchHit:
    """单条搜索结果。"""

    title: str
    snippet: str
    url: str = ""


@dataclass
class QuerySearchResult:
    """单次查询的结果与诊断信息。"""

    query: str
    hits: list[SearchHit] = field(default_factory=list)
    error: str = ""
    html_bytes: int = 0
    parsed_blocks: int = 0
    provider: str = ""


@dataclass
class WebGatherResult:
    """多轮联网检索汇总：条数 + 是否真连上 + 失败原因。"""

    hits: list[SearchHit] = field(default_factory=list)
    queries: list[QuerySearchResult] = field(default_factory=list)
    elapsed_ms: float = 0.0
    disabled: bool = False

    @property
    def hit_count(self) -> int:
        return len(self.hits)

    @property
    def queries_attempted(self) -> int:
        return len(self.queries)

    @property
    def queries_failed(self) -> int:
        return sum(1 for q in self.queries if q.error and not q.hits)

    @property
    def status(self) -> str:
        """ok | no_results | failed | skipped"""
        if self.disabled:
            return "skipped"
        if not self.queries:
            return "skipped"
        if self.queries_failed == self.queries_attempted:
            return "failed"
        if not self.hits:
            return "no_results"
        return "ok"

    def status_label(self) -> str:
        """供 UI 展示的人类可读联网状态。"""
        if self.disabled:
            return "联网已关闭（STUDIO_WEB_SEARCH=0）"
        n = self.queries_attempted
        if n == 0:
            return "未执行联网检索"
        providers = sorted({q.provider for q in self.queries if q.provider})
        via = f" via {','.join(providers)}" if providers else ""
        if self.status == "failed":
            err = self.queries[0].error if self.queries else "未知错误"
            return f"联网检索失败（{n} 次查询均未成功：{err}）"
        if self.status == "no_results":
            return f"联网 {self.hit_count} 条（已请求 {n} 次{via}，无匹配结果）"
        return f"联网 {self.hit_count} 条（{n} 次查询{via}）"


def _load_search_config(root: Path | None = None) -> dict:
    """读取 platform.yaml 中 research 段的搜索配置。"""
    if root is None:
        root = Path(__file__).resolve().parents[2]
    path = root / "config" / "platform.yaml"
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get("research") or {}


def _search_providers(root: Path | None = None) -> tuple[str, ...]:
    cfg = _load_search_config(root)
    raw = cfg.get("search_providers") or list(_DEFAULT_PROVIDERS)
    out: list[str] = []
    for name in raw:
        key = str(name).strip().lower()
        if key in ("bing", "duckduckgo", "ddg", "github") and key not in out:
            out.append("duckduckgo" if key == "ddg" else key)
    return tuple(out or _DEFAULT_PROVIDERS)


def _bing_host(root: Path | None = None) -> str:
    cfg = _load_search_config(root)
    host = str(cfg.get("search_bing_host") or "cn.bing.com").strip().rstrip("/")
    return host.replace("https://", "").replace("http://", "")


def _fetch_search_html(url: str) -> tuple[bytes, str | None]:
    """发起 HTTPS 请求；成功返回 (body, None)，失败返回 (b'', 错误描述)。"""
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return resp.read(), None
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        return b"", f"网络错误: {reason}"
    except TimeoutError:
        return b"", f"请求超时（>{_TIMEOUT}s）"
    except Exception as exc:
        return b"", f"{type(exc).__name__}: {exc}"


def _parse_duckduckgo_html(html: str, max_results: int) -> tuple[list[SearchHit], int, str]:
    """解析 DuckDuckGo HTML 结果页。"""
    blocks = re.findall(
        r'class="result__body"[^>]*>(.*?)</div>\s*</div>',
        html,
        flags=re.I | re.S,
    )
    if not blocks:
        lowered = html.lower()
        if "captcha" in lowered or "bot" in lowered or "anomaly" in lowered:
            return [], 0, "搜索页疑似触发反爬/验证码"
        if len(html) < 500:
            return [], 0, "搜索页内容过短，可能未连通"
        return [], 0, "搜索页已返回但未解析到结果（页面结构可能已变更）"

    hits: list[SearchHit] = []
    for block in blocks:
        title = ""
        link = ""
        title_m = re.search(
            r'class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
            block,
            flags=re.I | re.S,
        )
        if title_m:
            link = unescape(title_m.group(1))
            title = unescape(re.sub(r"<[^>]+>", " ", title_m.group(2)))
            title = re.sub(r"\s+", " ", title).strip()

        snippet = ""
        snip_m = re.search(
            r'class="result__snippet"[^>]*>(.*?)</(?:a|span|div)>',
            block,
            flags=re.I | re.S,
        )
        if snip_m:
            snippet = unescape(re.sub(r"<[^>]+>", " ", snip_m.group(1)))
            snippet = re.sub(r"\s+", " ", snippet).strip()

        if not snippet and not title:
            continue
        hits.append(SearchHit(title=title or snippet[:40], snippet=snippet or title, url=link))
        if len(hits) >= max_results:
            break
    if not hits:
        return [], len(blocks), "页面有结果块但未提取到有效条目"
    return hits, len(blocks), ""


def _parse_bing_html(html: str, max_results: int) -> tuple[list[SearchHit], int, str]:
    """解析 Bing 搜索结果页（cn.bing.com / www.bing.com）。"""
    lowered = html.lower()
    if ("turnstile" in lowered or "captcha" in lowered) and "b_algo" not in lowered:
        return [], 0, "Bing 返回验证码/反爬页，未拿到搜索结果"

    blocks = re.findall(r'<li class="b_algo"[\s\S]*?</li>', html, flags=re.I)
    if not blocks:
        return [], 0, "Bing 页面已返回但未解析到结果"

    hits: list[SearchHit] = []
    for block in blocks:
        title_m = re.search(
            r'<h2[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>([\s\S]*?)</a>',
            block,
            flags=re.I,
        )
        if not title_m:
            title_m = re.search(r'<a[^>]*href="([^"]+)"[^>]*>([\s\S]*?)</a>', block, flags=re.I)
        snippet_m = re.search(r'<p[^>]*>([\s\S]*?)</p>', block, flags=re.I)

        if not title_m:
            continue
        link = unescape(title_m.group(1))
        title = unescape(re.sub(r"<[^>]+>", " ", title_m.group(2)))
        title = re.sub(r"\s+", " ", title).strip()
        snippet = ""
        if snippet_m:
            snippet = unescape(re.sub(r"<[^>]+>", " ", snippet_m.group(1)))
            snippet = re.sub(r"\s+", " ", snippet).strip()

        if not title and not snippet:
            continue
        hits.append(SearchHit(title=title or snippet[:40], snippet=snippet or title, url=link))
        if len(hits) >= max_results:
            break
    if not hits:
        return [], len(blocks), "Bing 有结果块但未提取到有效条目"
    return hits, len(blocks), ""


def _simplify_query_for_github(query: str) -> str:
    """GitHub 搜索对中文长句不友好，提取英文/数字技术关键词。"""
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9+#\.\-/]*|\d+", query)
    stop = {"similar", "open", "source", "project", "github", "app", "the", "and", "for"}
    kept: list[str] = []
    for tok in tokens:
        low = tok.lower()
        if low in stop:
            continue
        if len(tok) <= 2 and not tok.isdigit():
            continue
        kept.append(tok)
    return " ".join(kept[:10])


def _search_github_api(query: str, max_results: int) -> QuerySearchResult:
    """GitHub 仓库搜索（国内网络通常比 DuckDuckGo 更稳定）。"""
    candidates = []
    simplified = _simplify_query_for_github(query)
    if simplified:
        candidates.append(simplified)
    if query not in candidates:
        candidates.append(query)

    last = QuerySearchResult(query=query, provider="github")
    for candidate in candidates:
        attempt = _fetch_github_repos(candidate, max_results)
        attempt.query = query
        attempt.provider = "github"
        if attempt.hits:
            return attempt
        last = attempt
    return last


def _fetch_github_repos(query: str, max_results: int) -> QuerySearchResult:
    """单次 GitHub Search API 调用。"""
    result = QuerySearchResult(query=query, provider="github")
    url = (
        "https://api.github.com/search/repositories?q="
        + urllib.parse.quote(query)
        + f"&sort=stars&per_page={max_results}"
    )
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _USER_AGENT,
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            raw = resp.read()
            result.html_bytes = len(raw)
            data = json.loads(raw.decode("utf-8"))
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        result.error = f"网络错误: {reason}"
        return result
    except TimeoutError:
        result.error = f"请求超时（>{_TIMEOUT}s）"
        return result
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        return result

    items = data.get("items") or []
    result.parsed_blocks = len(items)
    hits: list[SearchHit] = []
    for item in items:
        name = str(item.get("full_name") or item.get("name") or "")
        desc = str(item.get("description") or "")
        link = str(item.get("html_url") or "")
        if not name:
            continue
        hits.append(
            SearchHit(
                title=name,
                snippet=desc or f"GitHub stars: {item.get('stargazers_count', 0)}",
                url=link,
            )
        )
    result.hits = hits
    if not hits:
        result.error = "GitHub 未找到匹配仓库"
    return result


def _search_with_provider(
    provider: str,
    query: str,
    max_results: int,
    *,
    bing_host: str,
) -> QuerySearchResult:
    """按指定搜索引擎检索一次。"""
    if provider == "github":
        return _search_github_api(query, max_results)

    result = QuerySearchResult(query=query, provider=provider)
    if provider == "bing":
        url = f"https://{bing_host}/search?q=" + urllib.parse.quote(query)
        parse: Callable[[str, int], tuple[list[SearchHit], int, str]] = _parse_bing_html
    elif provider == "duckduckgo":
        url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
        parse = _parse_duckduckgo_html
    else:
        result.error = f"未知搜索引擎: {provider}"
        return result

    raw, fetch_err = _fetch_search_html(url)
    result.html_bytes = len(raw)
    if fetch_err:
        result.error = fetch_err
        return result

    html = raw.decode("utf-8", errors="ignore")
    hits, blocks, parse_err = parse(html, max_results)
    result.parsed_blocks = blocks
    result.hits = hits
    if parse_err and not hits:
        result.error = parse_err
    return result


def search_web(query: str, max_results: int = 5) -> list[str]:
    """兼容旧接口：仅返回摘要片段。"""
    return [h.snippet for h in search_web_detailed(query, max_results=max_results).hits]


def search_web_detailed(
    query: str,
    max_results: int = 5,
    *,
    root: Path | None = None,
) -> QuerySearchResult:
    """搜索并返回标题 + 摘要 + 链接；按配置依次尝试 Bing / DuckDuckGo。"""
    providers = _search_providers(root)
    bing_host = _bing_host(root)
    last = QuerySearchResult(query=query)
    errors: list[str] = []

    for provider in providers:
        attempt = _search_with_provider(
            provider, query, max_results, bing_host=bing_host
        )
        if attempt.hits:
            return attempt
        if not attempt.error:
            return attempt
        errors.append(f"{provider}: {attempt.error}")
        last = attempt

    if errors:
        last.error = "；".join(errors)
        last.provider = "+".join(providers)
    return last


def gather_web_research(
    description: str,
    queries: list[str] | None = None,
    *,
    root: Path | None = None,
) -> WebGatherResult:
    """对同一项目执行多轮搜索并去重，附带联网诊断。"""
    if queries is None:
        queries = [
            f"{description} 技术栈 开发方案",
            f"{description} 类似产品 开源项目",
            f"{description} similar open source github",
        ]
    started = time.perf_counter()
    seen: set[tuple[str, str]] = set()
    all_hits: list[SearchHit] = []
    query_results: list[QuerySearchResult] = []

    for q in queries:
        qr = search_web_detailed(q, max_results=4, root=root)
        query_results.append(qr)
        for hit in qr.hits:
            key = (hit.title, hit.snippet)
            if key in seen:
                continue
            seen.add(key)
            all_hits.append(hit)

    elapsed_ms = (time.perf_counter() - started) * 1000
    return WebGatherResult(hits=all_hits, queries=query_results, elapsed_ms=elapsed_ms)
