# core/research/mock.py — 关键词 mock 调研（web_search 不可用时的回退）
from __future__ import annotations

from core.research.keywords import format_keyword_line, keyword_hit_plain, match_keywords
from core.project import ORG_TEMPLATES


def _template_label(template_id: str) -> str:
    return str(ORG_TEMPLATES.get(template_id, {}).get("label", template_id))


def mock_research(description: str, *, tech_stack: str = "") -> dict[str, str | list[str] | bool]:
    """根据描述 + 可选技术栈返回 mock 调研结论。"""
    combined = description.strip()
    if tech_stack.strip():
        combined = f"{combined} {tech_stack.strip()}"

    kw = match_keywords(combined)
    if kw.hit and kw.template_id:
        return {
            "summary": (
                f"✓ 调研完成（关键词匹配）\n\n"
                f"项目：{description}\n"
                f"{keyword_hit_plain(kw)}\n"
                f"结论：{kw.note}\n"
                f"推荐组织：{_template_label(kw.template_id)}"
            ),
            "recommended_template": kw.template_id,
            "source": "keyword_match",
            "matched_keywords": kw.matched,
            "needs_tech_stack": False,
        }

    return {
        "summary": (
            f"⏳ 调研完成（未命中关键词）\n\n"
            f"项目：{description}\n"
            f"结论：描述中未识别到 Vue/React/小程序等技术关键词。\n"
            f"请在下方补充技术栈，或下一步手动选择组织模板。"
        ),
        "recommended_template": "web-fullstack",
        "source": "needs_tech_stack",
        "matched_keywords": [],
        "needs_tech_stack": True,
    }
