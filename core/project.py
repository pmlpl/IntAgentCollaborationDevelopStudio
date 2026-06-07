# core/project.py — 项目初始化与路径管理
from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

from core.org.tree_ops import OrgTree


def get_studio_root() -> Path:
    """定位 studio 根目录（含 config/agents.yaml）。"""
    cwd = Path.cwd()
    if (cwd / "config" / "agents.yaml").exists():
        return cwd
    # 从包位置向上找
    here = Path(__file__).resolve().parents[1]
    if (here / "config" / "agents.yaml").exists():
        return here
    return cwd


def default_positions(project_name: str) -> dict:
    """Phase 1 默认最小组织架构。"""
    return {
        "project": project_name,
        "description": f"{project_name} 项目",
        "created": date.today().isoformat(),
        "positions": [
            {
                "id": "laowang",
                "name": "老王",
                "title": "技术主管",
                "parent": None,
                "agent": "claude-code",
                "model": "deepseek-v4-pro",
                "is_manager": True,
                "resume": {"strengths": ["任务拆解", "技术决策", "代码审查"]},
            },
            {
                "id": "xiaohong",
                "name": "小红",
                "title": "前端开发",
                "parent": "laowang",
                "agent": "cursor",
                "model": "deepseek-v4-flash",
                "resume": {"strengths": ["Vue3组件", "Pinia", "Tailwind CSS"]},
            },
            {
                "id": "dazhuang",
                "name": "大壮",
                "title": "后端开发",
                "parent": "laowang",
                "agent": "hermes",
                "model": "deepseek-v4-pro",
                "resume": {"strengths": ["REST API", "数据库"]},
            },
            {
                "id": "xiaoyan",
                "name": "小严",
                "title": "测试审查",
                "parent": "laowang",
                "agent": "opencode",
                "model": "deepseek-v4-flash",
                "waits_on": ["xiaohong", "dazhuang"],
                "resume": {"strengths": ["代码审查", "端到端测试"]},
            },
        ],
    }


def init_project(root: Path, name: str, repo_path: Path | None = None) -> Path:
    """创建 projects/{name}/ 目录结构。"""
    project_dir = root / "projects" / name
    if project_dir.exists():
        raise FileExistsError(f"project already exists: {name}")

    positions_data = default_positions(name)
    project_dir.mkdir(parents=True)
    (project_dir / "shared").mkdir()
    (project_dir / "tasks" / "active").mkdir(parents=True)
    (project_dir / "tasks" / "archive").mkdir(parents=True)
    (project_dir / "workspaces").mkdir()

    positions_path = project_dir / "positions.yaml"
    positions_path.write_text(
        yaml.dump(positions_data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    tree = OrgTree.from_yaml_data(positions_data)
    for pos in tree.to_list():
        agent_dir = project_dir / "agents" / pos["id"]
        (agent_dir / "runtime").mkdir(parents=True)
        (agent_dir / "cache").mkdir()
        (agent_dir / "logs").mkdir()
        (agent_dir / "inbox" / "processed").mkdir(parents=True)

    ceo_dir = project_dir / "agents" / "__ceo__" / "inbox" / "processed"
    ceo_dir.mkdir(parents=True)

    if repo_path:
        meta = {"repo_path": str(repo_path.resolve())}
        (project_dir / "shared" / "repo.yaml").write_text(
            yaml.dump(meta, allow_unicode=True), encoding="utf-8"
        )

    return project_dir


def load_project(root: Path, name: str | None = None) -> Path:
    """加载当前项目目录。"""
    if name:
        project_dir = root / "projects" / name
        if not project_dir.exists():
            raise FileNotFoundError(f"project not found: {name}")
        return project_dir

    current_file = root / "projects" / ".current"
    if current_file.exists():
        current = current_file.read_text(encoding="utf-8").strip()
        project_dir = root / "projects" / current
        if project_dir.exists():
            return project_dir

    projects_root = root / "projects"
    if not projects_root.exists():
        raise FileNotFoundError("no projects directory")
    candidates = [p for p in projects_root.iterdir() if p.is_dir() and p.name != ".current"]
    if len(candidates) == 1:
        return candidates[0]
    raise FileNotFoundError("multiple projects; specify --project")


def set_current_project(root: Path, name: str) -> None:
    (root / "projects" / ".current").write_text(name, encoding="utf-8")
