# core/research/templates.py — 调研模板存档与相似匹配
from __future__ import annotations

import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import yaml

from core.project import ORG_TEMPLATES, get_studio_root


def templates_dir(root: Path | None = None) -> Path:
    """config/templates 目录。"""
    base = root or get_studio_root()
    return base / "config" / "templates"


def _tokenize(text: str) -> set[str]:
    parts = re.findall(r"[\w\u4e00-\u9fff]+", text.lower())
    return {p for p in parts if len(p) >= 2}


def list_saved_templates(root: Path | None = None) -> list[dict[str, Any]]:
    """列出已存档的调研模板。"""
    td = templates_dir(root)
    if not td.exists():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(td.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        data.setdefault("id", path.stem)
        items.append(data)
    return items


def find_similar_template(
    description: str,
    root: Path | None = None,
    *,
    threshold: float = 0.38,
) -> dict[str, Any] | None:
    """按关键词重叠找最相似已存档模板。"""
    desc_tokens = _tokenize(description)
    if not desc_tokens:
        return None
    best: dict[str, Any] | None = None
    best_score = 0.0
    desc_lower = description.lower()
    for tpl in list_saved_templates(root):
        keywords = tpl.get("keywords") or []
        kw_tokens = _tokenize(" ".join(str(k) for k in keywords))
        kw_tokens |= _tokenize(str(tpl.get("description", "")))
        if not kw_tokens:
            continue
        overlap = len(desc_tokens & kw_tokens) / max(len(desc_tokens | kw_tokens), 1)
        ratio = SequenceMatcher(None, description, str(tpl.get("description", ""))).ratio()
        keyword_hits = sum(
            1 for k in keywords if str(k).lower() in desc_lower or str(k).lower() in desc_tokens
        )
        hit_boost = min(keyword_hits * 0.12, 0.36)
        score = overlap * 0.55 + ratio * 0.25 + hit_boost
        if score > best_score:
            best_score = score
            best = tpl
    if best and best_score >= threshold:
        best = dict(best)
        best["match_score"] = round(best_score, 3)
        return best
    return None


def save_research_template(
    description: str,
    org_template: str,
    summary: str,
    root: Path | None = None,
    *,
    keywords: list[str] | None = None,
) -> Path:
    """将调研结果存档为 config/templates/<slug>.yaml。"""
    base = root or get_studio_root()
    td = templates_dir(base)
    td.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", description.lower()).strip("-")[:48]
    slug = slug or "project"
    path = td / f"{slug}.yaml"
    idx = 1
    while path.exists():
        path = td / f"{slug}-{idx}.yaml"
        idx += 1
    payload = {
        "id": path.stem,
        "description": description,
        "org_template": org_template,
        "summary": summary,
        "keywords": keywords or _extract_keywords(description),
    }
    path.write_text(yaml.dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def _extract_keywords(description: str) -> list[str]:
    return sorted(_tokenize(description))[:12]


def infer_org_template(text: str) -> str:
    """根据描述 + 调研文本推断 org 模板 id。"""
    lowered = text.lower()
    rules: list[tuple[list[str], str]] = [
        (["小程序", "微信", "uni", "miniprogram"], "web-miniprogram"),
        (["移动", "app", "ios", "android", "flutter", "react native"], "web-mobile"),
        (["桌面", "electron", "tauri", "desktop"], "multi-endpoint"),
        (["全端", "多端", "跨端"], "multi-endpoint"),
        (["mvp", "原型", "精小", "一人"], "minimal"),
    ]
    for keys, template_id in rules:
        if any(k in lowered for k in keys):
            return template_id
    if any(k in lowered for k in ["vue", "react", "fastapi", "全栈", "web", "后端", "前端"]):
        return "web-fullstack"
    return "web-fullstack"


def template_label(template_id: str) -> str:
    meta = ORG_TEMPLATES.get(template_id, {})
    return str(meta.get("label", template_id))
