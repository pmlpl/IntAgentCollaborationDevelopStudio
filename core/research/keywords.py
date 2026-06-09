# core/research/keywords.py — 调研关键词规则与命中检测
from __future__ import annotations

from dataclasses import dataclass, field

# (关键词列表, 组织模板 id, 说明)
KEYWORD_RULES: list[tuple[list[str], str, str]] = [
    (
        ["小程序", "微信", "uni-app", "uniapp", "miniprogram", "微信小程序"],
        "web-miniprogram",
        "小程序项目通常需要前端 + 小程序 + 后端 + 测试岗位。",
    ),
    (
        ["移动", "app", "ios", "android", "flutter", "react native", "rn", "kotlin", "swift"],
        "web-mobile",
        "移动 + Web 项目建议增加移动端开发岗位。",
    ),
    (
        ["桌面", "electron", "tauri", "desktop", "wpf"],
        "multi-endpoint",
        "多端项目建议 Web + 移动 + 桌面并行开发。",
    ),
    (
        ["全端", "多端", "跨端"],
        "multi-endpoint",
        "全端项目建议 Web、移动、小程序、桌面岗位协同。",
    ),
    (
        ["mvp", "原型", "精小", "一人", "solo"],
        "minimal",
        "精小团队适合主管 + 全栈一人快速迭代。",
    ),
    (
        [
            "vue",
            "vue3",
            "react",
            "nextjs",
            "nuxt",
            "fastapi",
            "django",
            "spring",
            "全栈",
            "web",
            "前端",
            "后端",
            "node",
            "nestjs",
            "gin",
            "golang",
            "python",
            "java",
            "typescript",
            "javascript",
        ],
        "web-fullstack",
        "Web 全栈项目推荐主管 + 前后端 + 测试的标准编制。",
    ),
]


@dataclass
class KeywordMatch:
    """关键词匹配结果。"""

    hit: bool
    matched: list[str] = field(default_factory=list)
    template_id: str | None = None
    note: str = ""


def match_keywords(text: str) -> KeywordMatch:
    """在文本中查找关键词；返回命中最多的一条规则。"""
    lowered = (text or "").lower()
    if not lowered.strip():
        return KeywordMatch(hit=False)

    best_hits: list[str] = []
    best_template: str | None = None
    best_note = ""
    best_score = 0

    for keys, template_id, note in KEYWORD_RULES:
        hits = [k for k in keys if k.lower() in lowered]
        if len(hits) > best_score:
            best_score = len(hits)
            best_hits = hits
            best_template = template_id
            best_note = note

    if best_score > 0 and best_template:
        # 去重并保持顺序
        seen: set[str] = set()
        unique: list[str] = []
        for h in best_hits:
            key = h.lower()
            if key not in seen:
                seen.add(key)
                unique.append(h)
        return KeywordMatch(
            hit=True,
            matched=unique,
            template_id=best_template,
            note=best_note,
        )
    return KeywordMatch(hit=False)


def keyword_hit_plain(match: KeywordMatch) -> str:
    """纯文本关键词行。"""
    if not match.hit:
        return "未命中预设关键词"
    return f"命中关键词：{'、'.join(match.matched)} → 推荐 {match.template_id}"


def format_keyword_line(match: KeywordMatch) -> str:
    """格式化关键词命中行，供 TUI 展示。"""
    if not match.hit:
        return "[yellow]未命中预设关键词[/]"
    words = "、".join(match.matched)
    return f"[green]✓ 命中关键词：{words}[/] → 推荐 [bold]{match.template_id}[/]"
