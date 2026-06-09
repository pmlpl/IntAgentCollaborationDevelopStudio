# core/project_profile.py — 项目画像 PROJECT.md（结构化 frontmatter + 摘要正文）
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

PROFILE_FILENAME = "PROJECT.md"


@dataclass
class ProjectProfile:
    """单项目长期画像，持久化于 .studio/PROJECT.md。"""

    description: str = ""
    domain: str = ""
    org_template: str = ""
    technologies_primary: list[str] = field(default_factory=list)
    technologies_alternate: list[str] = field(default_factory=list)
    similar_products: list[dict[str, str]] = field(default_factory=list)
    similar_local_template: str | None = None
    research_summary: str = ""
    updated_at: str = ""
    research_history: list[str] = field(default_factory=list)

    @property
    def has_substance(self) -> bool:
        return bool(
            self.technologies_primary
            or self.research_summary
            or self.domain
            or self.org_template
        )


def profile_path(project_dir: Path) -> Path:
    return project_dir / PROFILE_FILENAME


def load_profile(project_dir: Path) -> ProjectProfile | None:
    """读取 PROJECT.md；不存在或解析失败返回 None。"""
    path = profile_path(project_dir)
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    return parse_profile_markdown(text)


def parse_profile_markdown(text: str) -> ProjectProfile | None:
    """解析带 YAML frontmatter 的 PROJECT.md。"""
    text = text.strip()
    if not text:
        return None
    meta: dict[str, Any] = {}
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                meta = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                meta = {}
            body = parts[2].strip()

    summary = ""
    m = re.search(r"^#\s*调研摘要\s*\n+(.*)", body, flags=re.M | re.S)
    if m:
        summary = m.group(1).strip()
        nxt = re.search(r"\n#+\s", summary)
        if nxt:
            summary = summary[: nxt.start()].strip()

    local_tpl = meta.get("similar_local_template")
    if local_tpl in (None, "null", ""):
        local_tpl = None

    products = meta.get("similar_products") or []
    if not isinstance(products, list):
        products = []

    history = meta.get("research_history") or []
    if not isinstance(history, list):
        history = []

    return ProjectProfile(
        description=str(meta.get("description") or ""),
        domain=str(meta.get("domain") or ""),
        org_template=str(meta.get("org_template") or ""),
        technologies_primary=_as_str_list(meta.get("technologies_primary")),
        technologies_alternate=_as_str_list(meta.get("technologies_alternate")),
        similar_products=[
            {"name": str(p.get("name", "")), "note": str(p.get("note", ""))}
            for p in products
            if isinstance(p, dict)
        ],
        similar_local_template=str(local_tpl) if local_tpl else None,
        research_summary=summary or str(meta.get("research_summary") or ""),
        updated_at=str(meta.get("updated_at") or ""),
        research_history=[str(x) for x in history[-10:]],
    )


def _as_str_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [str(value).strip()]


def save_profile(project_dir: Path, profile: ProjectProfile) -> Path:
    """写入 PROJECT.md。"""
    project_dir.mkdir(parents=True, exist_ok=True)
    profile.updated_at = datetime.now(timezone.utc).isoformat()
    path = profile_path(project_dir)
    path.write_text(render_profile_markdown(profile), encoding="utf-8")
    return path


def render_profile_markdown(profile: ProjectProfile) -> str:
    """渲染 PROJECT.md 内容。"""
    meta = {
        "version": 1,
        "updated_at": profile.updated_at or datetime.now(timezone.utc).isoformat(),
        "description": profile.description,
        "domain": profile.domain,
        "org_template": profile.org_template,
        "technologies_primary": profile.technologies_primary,
        "technologies_alternate": profile.technologies_alternate,
        "similar_products": profile.similar_products,
        "similar_local_template": profile.similar_local_template,
        "research_history": profile.research_history[-10:],
    }
    fm = yaml.dump(meta, allow_unicode=True, sort_keys=False).strip()
    lines = [
        "---",
        fm,
        "---",
        "",
        "# 项目概述",
        "",
        profile.description or "（待补充）",
        "",
        "# 技术栈",
        "",
        "## 主选",
    ]
    if profile.technologies_primary:
        lines.extend(f"- {t}" for t in profile.technologies_primary)
    else:
        lines.append("- （待调研）")

    lines.extend(["", "## 备选"])
    if profile.technologies_alternate:
        lines.extend(f"- {t}" for t in profile.technologies_alternate)
    else:
        lines.append("- （暂无）")

    lines.extend(["", "# 业务域", "", profile.domain or "（待识别）", "", "# 调研摘要", ""])
    lines.append(profile.research_summary or "（暂无调研记录）")

    if profile.similar_products:
        lines.extend(["", "# 相似参考", ""])
        for p in profile.similar_products[:12]:
            name = p.get("name") or "未知"
            note = p.get("note") or ""
            lines.append(f"- **{name}**" + (f"：{note}" if note else ""))

    if profile.org_template:
        lines.extend(["", "# 组织决策", "", f"- 推荐模板：`{profile.org_template}`"])

    if profile.research_history:
        lines.extend(["", "# 调研历史", ""])
        lines.extend(f"- {h}" for h in profile.research_history[-8:])

    lines.append("")
    return "\n".join(lines)


def profile_context_for_prompt(profile: ProjectProfile | None) -> str:
    """供调研 Agent 阅读的画像摘要。"""
    if profile is None or not profile.has_substance:
        return "（尚无 PROJECT.md 画像，这是首次调研）"

    lines = [
        f"- 项目概述：{profile.description}",
        f"- 业务域：{profile.domain or '未知'}",
        f"- 已知主选技术栈：{', '.join(profile.technologies_primary) or '无'}",
        f"- 已知备选技术栈：{', '.join(profile.technologies_alternate) or '无'}",
        f"- 当前组织模板：{profile.org_template or '未确定'}",
    ]
    if profile.research_summary:
        lines.append(f"- 上次调研摘要：{profile.research_summary[:400]}")
    if profile.similar_products:
        refs = "；".join(
            f"{p.get('name', '')}" for p in profile.similar_products[:4] if p.get("name")
        )
        if refs:
            lines.append(f"- 已知相似参考：{refs}")
    lines.append(
        "请优先基于以上画像补充/修正，仅对缺失信息联网搜索；"
        "若用户本次描述与画像冲突，以最新描述为准并更新画像。"
    )
    return "\n".join(lines)


def _merge_unique(existing: list[str], new_items: list[str]) -> list[str]:
    seen = {x.lower() for x in existing}
    out = list(existing)
    for item in new_items:
        key = item.strip()
        if key and key.lower() not in seen:
            seen.add(key.lower())
            out.append(key)
    return out


def merge_research_into_profile(
    profile: ProjectProfile | None,
    *,
    description: str,
    technologies: list[str] | None = None,
    technologies_alternate: list[str] | None = None,
    similar_products: list[dict[str, str]] | None = None,
    similar_local_template: str | None = None,
    org_template: str = "",
    summary: str = "",
    domain: str = "",
) -> ProjectProfile:
    """将调研结果合并进画像（去重、保留历史）。"""
    base = profile or ProjectProfile(description=description)
    if description.strip():
        base.description = description.strip()
    if domain.strip():
        base.domain = domain.strip()
    if org_template:
        base.org_template = org_template
    if technologies:
        base.technologies_primary = _merge_unique(base.technologies_primary, technologies)
    if technologies_alternate:
        base.technologies_alternate = _merge_unique(
            base.technologies_alternate, technologies_alternate
        )
    if similar_products:
        seen = {(p.get("name") or "").lower() for p in base.similar_products}
        for p in similar_products:
            name = (p.get("name") or "").strip()
            if name and name.lower() not in seen:
                seen.add(name.lower())
                base.similar_products.append(
                    {"name": name, "note": str(p.get("note") or "")[:200]}
                )
    if similar_local_template:
        base.similar_local_template = similar_local_template
    if summary.strip():
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        base.research_summary = summary.strip()
        note = f"{stamp}：{summary.strip()[:120]}"
        if note not in base.research_history:
            base.research_history.append(note)
    return base


def update_profile_from_report(
    project_dir: Path,
    report: Any,
    *,
    description: str = "",
) -> Path:
    """从 ResearchReport 更新 PROJECT.md。"""
    existing = load_profile(project_dir)
    domain = str(getattr(report, "domain", "") or "")
    alt = list(getattr(report, "technologies_alternate", []) or [])

    merged = merge_research_into_profile(
        existing,
        description=description or getattr(report, "description", ""),
        technologies=list(getattr(report, "technologies", []) or []),
        technologies_alternate=alt,
        similar_products=list(getattr(report, "similar_products", []) or []),
        similar_local_template=getattr(report, "similar_local_template", None),
        org_template=str(getattr(report, "recommended_template", "") or ""),
        summary=str(getattr(report, "summary", "") or ""),
        domain=domain,
    )
    return save_profile(project_dir, merged)


def update_profile_from_dict(project_dir: Path, data: dict[str, Any], description: str) -> Path:
    """从 research_project 返回 dict 更新 PROJECT.md。"""
    existing = load_profile(project_dir)
    raw_summary = str(data.get("summary") or "")
    for tag in ("[bold cyan]", "[/]", "[bold]", "[dim]", "[green]", "[yellow]"):
        raw_summary = raw_summary.replace(tag, "")
    merged = merge_research_into_profile(
        existing,
        description=description,
        technologies=list(data.get("technologies") or []),
        technologies_alternate=list(data.get("technologies_alternate") or []),
        similar_products=list(data.get("similar_products") or []),
        similar_local_template=data.get("similar_local_template"),  # type: ignore[arg-type]
        org_template=str(data.get("recommended_template") or ""),
        summary=raw_summary,
        domain=str(data.get("domain") or ""),
    )
    return save_profile(project_dir, merged)


def create_stub_profile(project_dir: Path, description: str) -> Path:
    """新建项目时写入初始 PROJECT.md。"""
    profile = ProjectProfile(description=description.strip() or "新项目")
    return save_profile(project_dir, profile)
