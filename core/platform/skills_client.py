# core/platform/skills_client.py — Skills 注册表与防线一加载
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from core.org.tree_ops import OrgTree
from core.platform.mcp_client import resolve_mcp_for_position, write_mcp_allowlist
from core.rbac.permission import effective_skill_use


class SkillsError(Exception):
    """Skills 中台异常。"""


def registry_path(root: Path) -> Path:
    return root / "platform" / "skills" / "registry.yaml"


def load_skills_registry(root: Path) -> dict[str, dict[str, Any]]:
    """读取技能注册表，返回 id → meta。"""
    path = registry_path(root)
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    items = data.get("skills") or []
    return {item["id"]: item for item in items if item.get("id")}


def list_skills(root: Path) -> list[dict[str, Any]]:
    """列出全部已注册技能。"""
    return sorted(load_skills_registry(root).values(), key=lambda x: x.get("id", ""))


def _load_org_tree(project_dir: Path | None) -> OrgTree | None:
    if project_dir is None:
        return None
    pos_path = project_dir / "positions.yaml"
    if not pos_path.exists():
        return None
    data = yaml.safe_load(pos_path.read_text(encoding="utf-8"))
    return OrgTree.from_yaml_data(data)


def resolve_skills_for_position(
    root: Path,
    position: dict[str, Any],
    *,
    tree: OrgTree | None = None,
) -> list[str]:
    """按岗位 resume.skills + RBAC 解析可用技能 id。"""
    registry = load_skills_registry(root)
    registry_ids = set(registry)
    if tree is None:
        resume = position.get("resume") or {}
        declared = resume.get("skills") or []
        return [sid for sid in declared if sid in registry]
    allowed = effective_skill_use(tree, position, registry_ids)
    return sorted(allowed)


def skill_package_path(root: Path, skill_id: str) -> Path | None:
    """技能包目录绝对路径。"""
    meta = load_skills_registry(root).get(skill_id)
    if not meta:
        return None
    rel = meta.get("package") or f"packages/{skill_id}"
    return (root / "platform" / "skills" / rel).resolve()


def write_skills_manifest(
    runtime_dir: Path,
    root: Path,
    skill_ids: list[str],
    mcp_servers: list[str],
) -> Path:
    """写入 agents/{id}/runtime/skills.manifest.yaml（Supervisor / Worker 读取）。"""
    runtime_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for sid in skill_ids:
        pkg = skill_package_path(root, sid)
        meta = load_skills_registry(root).get(sid, {})
        entries.append(
            {
                "id": sid,
                "name": meta.get("name", sid),
                "path": str(pkg) if pkg else "",
            }
        )
    manifest = {
        "skills": entries,
        "mcp_servers": mcp_servers,
    }
    path = runtime_dir / "skills.manifest.yaml"
    path.write_text(yaml.dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def prepare_worker_runtime(
    root: Path,
    project_dir: Path,
    position_id: str,
    position: dict[str, Any],
) -> tuple[list[str], list[str]]:
    """防线一：RBAC 过滤 skills/MCP，写入 manifest 与 allowlist。"""
    tree = _load_org_tree(project_dir)
    skills = resolve_skills_for_position(root, position, tree=tree)
    mcp_servers = resolve_mcp_for_position(root, position, tree=tree)
    runtime_dir = project_dir / "agents" / position_id / "runtime"
    write_skills_manifest(runtime_dir, root, skills, mcp_servers)
    write_mcp_allowlist(runtime_dir, mcp_servers, root)
    return skills, mcp_servers


def format_team_skills_line(root: Path, position: dict[str, Any], *, tree: OrgTree | None = None) -> str:
    """主管拆解 prompt 用的技能摘要行。"""
    skills = resolve_skills_for_position(root, position, tree=tree)
    mcp = resolve_mcp_for_position(root, position, tree=tree)
    parts = []
    if skills:
        parts.append(f"skills={skills}")
    if mcp:
        parts.append(f"mcp={mcp}")
    return " ".join(parts)
