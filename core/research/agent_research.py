# core/research/agent_research.py — 调研 Agent：联网搜索 + AI 综合分析
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from agents.chat_agent import AgentConfig, chat_agent_respond
from agents.runner import agent_available, run_agent_prompt_capture
from core.project import ORG_TEMPLATES, get_studio_root, list_all_role_ids
from core.research.local_llm import local_llm_available, run_local_prompt_capture
from core.project_profile import (
    ProjectProfile,
    load_profile,
    profile_context_for_prompt,
    update_profile_from_report,
)
from core.research.templates import find_similar_template, infer_org_template, list_saved_templates, save_research_template, template_label
from core.research.web_search import SearchHit, WebGatherResult, gather_web_research

RESEARCH_MARKER = "---STUDIO_RESEARCH_JSON---"
VALID_TEMPLATES = tuple(ORG_TEMPLATES.keys())


@dataclass
class ResearchReport:
    """调研 Agent 结构化报告。"""

    description: str
    technologies: list[str] = field(default_factory=list)
    technologies_alternate: list[str] = field(default_factory=list)
    domain: str = ""
    similar_products: list[dict[str, str]] = field(default_factory=list)
    similar_local_template: str | None = None
    recommended_template: str = "web-fullstack"
    recommended_roles: list[str] = field(default_factory=list)
    summary: str = ""
    source: str = "agent"
    web_hits: list[SearchHit] = field(default_factory=list)
    web_gather: WebGatherResult | None = None
    agent_available: bool = True
    needs_user_input: bool = False


def load_research_config(root: Path | None = None) -> dict[str, Any]:
    """读取 config/platform.yaml 中的 research 段。"""
    base = root or get_studio_root()
    path = base / "config" / "platform.yaml"
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get("research") or {}


def _research_agent_key(root: Path) -> str:
    cfg = load_research_config(root)
    return str(cfg.get("agent", "opencode"))


def _research_mode(root: Path) -> str:
    """调研 LLM 模式：offline | lmstudio | ollama | agent。"""
    env = os.environ.get("STUDIO_RESEARCH_MODE", "").strip().lower()
    if env in ("offline", "lmstudio", "ollama", "agent", "local", "none", "openai_compatible"):
        if env == "local":
            return "agent"
        if env == "none":
            return "offline"
        if env == "openai_compatible":
            return "lmstudio"
        return env
    cfg = load_research_config(root)
    mode = str(cfg.get("mode", "agent")).strip().lower()
    if mode == "local":
        return "agent"
    if mode == "none":
        return "offline"
    if mode in ("offline", "lmstudio", "ollama", "agent", "openai_compatible"):
        if mode == "openai_compatible":
            return "lmstudio"
        return mode
    return "agent"


def _search_queries(
    description: str,
    root: Path,
    tech_stack: str = "",
    profile: ProjectProfile | None = None,
) -> list[str]:
    cfg = load_research_config(root)
    combined = f"{description} {tech_stack}".strip()

    # 已有画像时：搜索更聚焦，避免重复泛搜
    if profile and profile.has_substance and not tech_stack.strip():
        queries: list[str] = []
        if len(profile.technologies_primary) < 2:
            queries.append(f"{combined} 技术栈 开发方案")
        else:
            primary = ", ".join(profile.technologies_primary[:4])
            queries.append(f"{description} {primary} 实现方案 最佳实践")
        if profile.domain:
            queries.append(f"{description} {profile.domain} 类似产品 开源")
        else:
            queries.append(f"{combined} 类似产品 开源项目")
        queries.append(f"{description} similar open source github")
        return queries[:3]

    templates = cfg.get("search_queries") or [
        "{desc} 技术栈 开发方案",
        "{desc} 类似产品 开源",
        "{desc} similar open source project",
    ]
    return [t.format(desc=combined) for t in templates]


def parse_research_output(stdout: str) -> dict[str, Any]:
    """从 Agent stdout 解析调研 JSON。"""
    if RESEARCH_MARKER not in stdout:
        raise ValueError(f"missing marker {RESEARCH_MARKER!r} in research output")
    _, raw = stdout.split(RESEARCH_MARKER, 1)
    data = json.loads(raw.strip())
    if not isinstance(data, dict):
        raise ValueError("research JSON must be an object")
    return data


def _role_catalog_for_prompt() -> str:
    """岗位目录摘要，供调研 Agent 选择 recommended_roles。"""
    from core.project import get_role_catalog

    catalog = get_role_catalog()
    lines: list[str] = []
    for rid in list_all_role_ids():
        meta = catalog.get(rid) or {}
        lines.append(f"- {rid}: {meta.get('name')} · {meta.get('title')}")
    return "\n".join(lines)


def _normalize_role_ids(raw: Any, description: str, template_id: str) -> list[str]:
    """校验并补全 recommended_roles。"""
    from core.project import get_role_catalog

    catalog = get_role_catalog()
    roles: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            rid = str(item).strip()
            if rid in catalog and rid not in roles:
                roles.append(rid)
    if "laowang" not in roles and "laowang" in catalog:
        roles.insert(0, "laowang")
    if not roles:
        roles = list(ORG_TEMPLATES.get(template_id, ORG_TEMPLATES["web-fullstack"])["roles"])
    return roles


def load_research_prompt_prefix(root: Path | None = None) -> str:
    """读取 config 中可选的调研提示词前缀（prompt_file）。"""
    cfg = load_research_config(root)
    rel = str(cfg.get("prompt_file") or "").strip()
    if not rel:
        return ""
    base = root or get_studio_root()
    path = (base / rel).resolve()
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip() + "\n\n"


def _normalize_report(
    description: str,
    data: dict[str, Any],
    *,
    web_hits: list[SearchHit],
    source: str,
    agent_ok: bool,
) -> ResearchReport:
    tpl = str(data.get("recommended_template") or "web-fullstack")
    if tpl not in VALID_TEMPLATES:
        tpl = infer_org_template(description + " " + json.dumps(data, ensure_ascii=False))

    local_tpl = data.get("similar_local_template")
    if local_tpl in (None, "null", ""):
        local_tpl = None
    else:
        local_tpl = str(local_tpl)

    techs = data.get("technologies") or []
    if not isinstance(techs, list):
        techs = [str(techs)]
    alt = data.get("technologies_alternate") or []
    if not isinstance(alt, list):
        alt = [str(alt)] if alt else []
    products = data.get("similar_products") or []
    if not isinstance(products, list):
        products = []

    summary = str(data.get("summary") or "").strip()
    roles = _normalize_role_ids(data.get("recommended_roles"), description, tpl)
    return ResearchReport(
        description=description,
        technologies=[str(t) for t in techs],
        technologies_alternate=[str(t) for t in alt],
        domain=str(data.get("domain") or "").strip(),
        similar_products=[
            {"name": str(p.get("name", "")), "note": str(p.get("note", ""))}
            for p in products
            if isinstance(p, dict)
        ],
        similar_local_template=local_tpl,
        recommended_template=tpl,
        recommended_roles=roles,
        summary=summary,
        source=source,
        web_hits=web_hits,
        agent_available=agent_ok,
        needs_user_input=not summary and not techs,
    )


def _format_web_section(hits: list[SearchHit], gather: WebGatherResult | None = None) -> str:
    if not hits:
        if gather and gather.status == "failed":
            return f"（联网检索失败：{gather.status_label()}，请根据常识推断）"
        if gather and gather.disabled:
            return "（联网检索已关闭，请根据常识推断）"
        return "（联网搜索未返回结果，请根据常识推断）"
    lines = []
    for i, h in enumerate(hits[:12], 1):
        url_part = f"\n   链接: {h.url}" if h.url else ""
        lines.append(f"{i}. {h.title}\n   {h.snippet}{url_part}")
    return "\n".join(lines)


def _format_local_section(root: Path | None, description: str) -> str:
    if root is None:
        return "（无本地模板库）"
    similar = find_similar_template(description, root)
    saved = list_saved_templates(root)
    lines = []
    if similar:
        lines.append(
            f"- 最相似存档: {similar.get('id')} "
            f"(匹配度 {similar.get('match_score', 0):.0%}) "
            f"→ 组织模板 {similar.get('org_template')}"
        )
    if saved:
        lines.append("- 全部存档模板:")
        for tpl in saved[:8]:
            lines.append(f"  · {tpl.get('id')}: {tpl.get('description', '')[:60]}")
    else:
        lines.append("（暂无存档模板）")
    return "\n".join(lines)


def build_research_prompt(
    description: str,
    web_hits: list[SearchHit],
    root: Path | None,
    *,
    tech_stack: str = "",
    profile: ProjectProfile | None = None,
    web_gather: WebGatherResult | None = None,
) -> str:
    """构建发给调研 Agent 的 prompt。"""
    extra = f"\n用户补充技术倾向：{tech_stack}" if tech_stack.strip() else ""
    template_ids = ", ".join(VALID_TEMPLATES)
    role_catalog = _role_catalog_for_prompt()
    profile_block = profile_context_for_prompt(profile)
    prefix = load_research_prompt_prefix(root)
    return (
        f"{prefix}"
        f"你是 Studio 平台的项目调研专员。请基于【项目画像】、联网搜索结果与岗位目录，"
        f"分析用户要做的项目，输出技术栈、相似产品、**推荐岗位编制**。\n\n"
        f"## 项目描述（本次输入）\n{description}{extra}\n\n"
        f"## 项目画像 PROJECT.md\n{profile_block}\n\n"
        f"## 联网搜索结果\n{_format_web_section(web_hits, web_gather)}\n\n"
        f"## 平台已有相似项目模板\n{_format_local_section(root, description)}\n\n"
        f"## 可选岗位目录（recommended_roles 只能从中选 id）\n{role_catalog}\n\n"
        f"## 要求\n"
        f"1. technologies 为主选技术栈，technologies_alternate 为备选方案\n"
        f"2. domain 为业务域（如：休闲游戏、电商、企业内部工具）\n"
        f"3. 列出相似产品或开源实现（没有则写空数组）\n"
        f"4. 判断是否与平台存档模板相似（similar_local_template）\n"
        f"5. recommended_roles：根据项目实际需要勾选岗位 id 列表，必须含 laowang\n"
        f"6. recommended_template：参考用，从 {template_ids} 中选最接近的一项\n"
        f"7. summary 用中文，说明推荐理由与不确定项\n\n"
        f"在回复末尾输出 JSON（严格遵守格式）：\n"
        f"{RESEARCH_MARKER}\n"
        f'{{"technologies":["..."],"technologies_alternate":["..."],"domain":"...",'
        f'"similar_products":[{{"name":"...","note":"..."}}],'
        f'"similar_local_template":null,'
        f'"recommended_roles":["laowang","xiaohong","dazhuang","xiaoyan"],'
        f'"recommended_template":"web-fullstack",'
        f'"summary":"..."}}'
    )


def _offline_synthesize(
    description: str,
    web_hits: list[SearchHit],
    root: Path | None,
    *,
    tech_stack: str = "",
) -> ResearchReport:
    """Agent 不可用时：用搜索结果 + 规则离线合成。"""
    combined = description + " " + tech_stack + " " + " ".join(h.snippet for h in web_hits)
    tpl = infer_org_template(combined)
    similar = find_similar_template(description, root) if root else None
    local_id = str(similar.get("id")) if similar else None
    roles = list(ORG_TEMPLATES.get(tpl, ORG_TEMPLATES["web-fullstack"])["roles"])

    # 从搜索结果标题提取「相似产品」
    products: list[dict[str, str]] = []
    for h in web_hits[:5]:
        if h.title:
            products.append({"name": h.title[:80], "note": h.snippet[:120]})

    techs: list[str] = []
    if tech_stack.strip():
        techs = [t.strip() for t in tech_stack.replace("，", ",").split(",") if t.strip()]

    summary = (
        f"离线调研（调研 Agent 未可用或未返回有效 JSON）。\n"
        f"根据联网检索与规则推断，推荐组织：{template_label(tpl)}。"
    )
    if similar:
        summary += f"\n平台内发现相似存档「{local_id}」，可考虑复用。"

    return ResearchReport(
        description=description,
        technologies=techs,
        technologies_alternate=[],
        domain="",
        similar_products=products,
        similar_local_template=local_id,
        recommended_template=tpl,
        recommended_roles=roles,
        summary=summary,
        source="offline",
        web_hits=web_hits,
        agent_available=False,
        needs_user_input=not web_hits and not tech_stack,
    )


def format_report_for_ui(report: ResearchReport) -> str:
    """渲染给用户看的调研报告文本（Rich markup）。"""
    src_label = {
        "agent": "调研 Agent + 联网",
        "local": "本地模型 + 联网",
        "offline": "联网 + 离线规则",
        "mock": "离线回退",
    }.get(report.source, report.source)

    lines = [
        f"[bold cyan]✓ 调研完成（{src_label}）[/]",
        "",
        f"[bold]项目[/] {report.description}",
        "",
        "[bold]推荐技术栈[/]",
    ]
    if report.technologies:
        lines.extend(f"  · {t}" for t in report.technologies)
    else:
        lines.append("  [dim]（Agent 未给出，可补充技术倾向后重新调研）[/]")

    if report.technologies_alternate:
        lines.extend(["", "[bold]备选技术栈[/]"])
        lines.extend(f"  · {t}" for t in report.technologies_alternate)

    if report.domain:
        lines.extend(["", f"[bold]业务域[/] {report.domain}"])

    lines.extend(["", "[bold]相似产品 / 开源参考[/]"])
    if report.similar_products:
        for p in report.similar_products[:6]:
            name = p.get("name") or "未知"
            note = p.get("note") or ""
            lines.append(f"  · {name}")
            if note:
                lines.append(f"    [dim]{note[:100]}[/]")
    else:
        lines.append("  [dim]未检索到明显相似项[/]")

    if report.similar_local_template:
        lines.extend(
            [
                "",
                f"[bold]平台相似存档[/] [green]{report.similar_local_template}[/]（建议复用）",
            ]
        )

    lines.extend(
        [
            "",
            f"[bold]推荐组织[/] {template_label(report.recommended_template)}",
        ]
    )
    if report.recommended_roles:
        from core.project import get_role_catalog

        catalog = get_role_catalog()
        role_labels = [
            f"{catalog[r]['name']}({r})"
            for r in report.recommended_roles
            if r in catalog
        ]
        lines.extend(["", "[bold]推荐岗位[/] " + " · ".join(role_labels)])

    lines.extend(["", report.summary or ""])

    if report.web_hits and report.source in ("agent", "local"):
        lines.extend(["", "[dim]--- 检索来源 ---[/]"])
        for h in report.web_hits[:4]:
            lines.append(f"[dim]· {h.title[:50]}[/]")

    return "\n".join(lines)


def _try_chat_model_research(
    desc: str,
    web_hits: list[SearchHit],
    template_root: Path,
    platform_root: Path,
    *,
    tech_stack: str = "",
    profile: ProjectProfile | None = None,
    web_gather: WebGatherResult | None = None,
) -> ResearchReport | None:
    """用聊天配置的模型执行调研（优先于外部 CLI agent）。"""
    chat_settings_path = platform_root / "config" / "chat_settings.yaml"
    if not chat_settings_path.is_file():
        return None

    try:
        settings_data = yaml.safe_load(chat_settings_path.read_text(encoding="utf-8")) or {}
        chat_model = settings_data.get("chat_model", {})
        model = str(chat_model.get("model", "")).strip()
        api_key = str(chat_model.get("api_key", "")).strip()
        base_url = str(chat_model.get("base_url", "")).strip()
    except Exception:
        return None

    if not model or not api_key:
        return None

    prompt = build_research_prompt(
        desc, web_hits, template_root,
        tech_stack=tech_stack, profile=profile, web_gather=web_gather,
    )

    config = AgentConfig(
        model=model,
        api_key=api_key,
        base_url=base_url,
        system_prompt="",
        max_tokens=4096,
        temperature=0.3,
    )

    try:
        output = chat_agent_respond(config, prompt)
    except Exception:
        return None

    if not output.strip():
        return None

    try:
        data = parse_research_output(output)
        report = _normalize_report(
            desc, data, web_hits=web_hits, source="agent", agent_ok=True
        )
        if web_gather:
            report.web_gather = web_gather
        return report
    except (ValueError, json.JSONDecodeError):
        return None


def run_agent_research(
    description: str,
    root: Path | None = None,
    *,
    project_dir: Path | None = None,
    tech_stack: str = "",
    force_offline: bool = False,
) -> ResearchReport:
    """执行完整调研：读 PROJECT.md → 联网 → 调研 Agent → 写回 PROJECT.md。"""
    platform_root = get_studio_root()
    template_root = root or platform_root
    desc = description.strip() or "新项目"
    profile = load_profile(project_dir) if project_dir else None

    web_gather = gather_web_research(
        desc, _search_queries(desc, platform_root, tech_stack, profile), root=platform_root
    )
    if os.environ.get("STUDIO_WEB_SEARCH", "1").lower() in ("0", "false", "no"):
        web_gather = WebGatherResult(
            hits=[],
            queries=web_gather.queries,
            elapsed_ms=web_gather.elapsed_ms,
            disabled=True,
        )
    web_hits = web_gather.hits

    mode = _research_mode(platform_root)
    if os.environ.get("STUDIO_RESEARCH_MOCK", "").lower() in ("1", "true", "yes"):
        mode = "offline"
    if force_offline:
        mode = "offline"

    agent_key = _research_agent_key(platform_root)
    report: ResearchReport | None = None

    if mode in ("lmstudio", "ollama"):
        prompt = build_research_prompt(
            desc,
            web_hits,
            template_root,
            tech_stack=tech_stack,
            profile=profile,
            web_gather=web_gather,
        )
        if local_llm_available(mode, platform_root):
            rc, output = run_local_prompt_capture(prompt, mode, platform_root)
            if rc == 0 and output.strip():
                try:
                    data = parse_research_output(output)
                    report = _normalize_report(
                        desc, data, web_hits=web_hits, source="local", agent_ok=True
                    )
                    report.web_gather = web_gather
                except (ValueError, json.JSONDecodeError):
                    report = None
        # 本地模型不可用时回退离线，不自动调用 Claude 以免浪费 token

    elif mode == "agent":
        # 优先使用聊天配置的模型（更可靠，不依赖外部 CLI）
        if not force_offline:
            report = _try_chat_model_research(
                desc, web_hits, template_root, platform_root,
                tech_stack=tech_stack, profile=profile, web_gather=web_gather,
            )

        # 回退到 opencode CLI agent
        if report is None and agent_available(platform_root, agent_key):
            prompt = build_research_prompt(
                desc,
                web_hits,
                template_root,
                tech_stack=tech_stack,
                profile=profile,
                web_gather=web_gather,
            )
            rc, output = run_agent_prompt_capture(
                platform_root, agent_key, prompt, cwd=platform_root
            )
            if rc == 0 and output.strip():
                try:
                    data = parse_research_output(output)
                    report = _normalize_report(
                        desc, data, web_hits=web_hits, source="agent", agent_ok=True
                    )
                    report.web_gather = web_gather
                except (ValueError, json.JSONDecodeError):
                    report = None

    if report is None:
        report = _offline_synthesize(desc, web_hits, template_root, tech_stack=tech_stack)
        report.web_gather = web_gather
    elif report.web_gather is None:
        report.web_gather = web_gather

    if template_root is not None:
        save_research_template(
            desc,
            report.recommended_template,
            report.summary,
            template_root,
            keywords=report.technologies or ([tech_stack] if tech_stack else None),
        )

    if project_dir is not None:
        update_profile_from_report(project_dir, report, description=desc)

    return report


def report_to_result_dict(report: ResearchReport) -> dict[str, Any]:
    """转换为 research_project 兼容 dict。"""
    return {
        "summary": format_report_for_ui(report),
        "recommended_template": report.recommended_template,
        "recommended_roles": report.recommended_roles,
        "source": report.source,
        "technologies": report.technologies,
        "technologies_alternate": report.technologies_alternate,
        "domain": report.domain,
        "similar_products": report.similar_products,
        "similar_local_template": report.similar_local_template,
        "matched_keywords": report.technologies,
        "needs_tech_stack": report.needs_user_input,
        "web_hit_count": len(report.web_hits),
        "web_search_status": (
            report.web_gather.status if report.web_gather else "unknown"
        ),
        "web_search_label": (
            report.web_gather.status_label() if report.web_gather else "联网状态未知"
        ),
        "web_search_elapsed_ms": (
            int(report.web_gather.elapsed_ms) if report.web_gather else 0
        ),
        "web_queries_failed": (
            report.web_gather.queries_failed if report.web_gather else 0
        ),
        "agent_available": report.agent_available,
    }
