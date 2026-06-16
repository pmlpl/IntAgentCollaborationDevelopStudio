# core/project.py — 项目初始化、registry 与路径管理
from __future__ import annotations

import re
import shutil
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from core.org.tree_ops import OrgTree

# 项目数据目录名：放在用户选的项目根目录下，不进 Git
DATA_DIR_NAME = ".studio"

# 默认 Web 全栈四人组（主管 + 前后端 + 测试）
_BASE_ROLES: list[dict[str, Any]] = [
    {
        "id": "laowang",
        "name": "老王",
        "title": "技术主管",
        "parent": None,
        "agent": "opencode",
        "model": "deepseek-v4-pro",
        "is_manager": True,
        "resume": {"strengths": ["任务拆解", "技术决策", "代码审查"]},
    },
    {
        "id": "xiaohong",
        "name": "小红",
        "title": "前端开发",
        "parent": "laowang",
        "agent": "opencode",
        "model": "deepseek-v4-flash",
        "resume": {"strengths": ["Vue3组件", "Pinia", "Tailwind CSS"], "skills": ["vue-debug"]},
    },
    {
        "id": "dazhuang",
        "name": "大壮",
        "title": "后端开发",
        "parent": "laowang",
        "agent": "hermes",
        "model": "deepseek-v4-pro",
        "resume": {
            "strengths": ["REST API", "数据库"],
            "skills": ["fastapi-expert", "python-async"],
            "mcp_servers": ["postgres-mcp"],
        },
    },
    {
        "id": "xiaoyan",
        "name": "小严",
        "title": "测试审查",
        "parent": "laowang",
        "agent": "aider",
        "model": "deepseek-v4-flash",
        "waits_on": ["xiaohong", "dazhuang"],
        "resume": {"strengths": ["代码审查", "端到端测试"], "skills": ["vue-debug"]},
    },
]

# 可选岗位（移动端 / 小程序 / 桌面端）
_EXTRA_ROLES: dict[str, dict[str, Any]] = {
    "xiaomo": {
        "id": "xiaomo",
        "name": "小默",
        "title": "移动端开发",
        "parent": "laowang",
        "agent": "opencode",
        "model": "deepseek-v4-flash",
        "resume": {"strengths": ["React Native", "Flutter", "iOS/Android"]},
    },
    "xiaocheng": {
        "id": "xiaocheng",
        "name": "小程",
        "title": "小程序开发",
        "parent": "laowang",
        "agent": "hermes",
        "model": "deepseek-v4-flash",
        "resume": {"strengths": ["微信小程序", "uni-app", "云开发"]},
    },
    "xiaozhuo": {
        "id": "xiaozhuo",
        "name": "小卓",
        "title": "桌面端开发",
        "parent": "laowang",
        "agent": "goose",
        "model": "deepseek-v4-flash",
        "resume": {"strengths": ["Electron", "Tauri", "桌面 UI"]},
    },
}

# 组织架构模板（Phase 1.5 向导用；完整逐岗编辑留 Phase 2）
ORG_TEMPLATES: dict[str, dict[str, Any]] = {
    "web-fullstack": {
        "label": "Web 全栈（主管 + 前后端 + 测试）",
        "roles": ["laowang", "xiaohong", "dazhuang", "xiaoyan"],
    },
    "web-mobile": {
        "label": "Web + 移动端",
        "roles": ["laowang", "xiaohong", "dazhuang", "xiaoyan", "xiaomo"],
    },
    "web-miniprogram": {
        "label": "Web + 小程序",
        "roles": ["laowang", "xiaohong", "dazhuang", "xiaoyan", "xiaocheng"],
    },
    "multi-endpoint": {
        "label": "全端（Web + 移动 + 小程序 + 桌面）",
        "roles": [
            "laowang",
            "xiaohong",
            "dazhuang",
            "xiaoyan",
            "xiaomo",
            "xiaocheng",
            "xiaozhuo",
        ],
    },
    "minimal": {
        "label": "精小团队（主管 + 全栈一人）",
        "roles": ["laowang", "xiaohong"],
    },
}


def list_org_templates() -> list[tuple[str, str]]:
    """返回 (template_id, 显示名) 列表，供 TUI Select 使用。"""
    return [(tid, meta["label"]) for tid, meta in ORG_TEMPLATES.items()]


def get_studio_root() -> Path:
    """定位 studio 平台根目录（含 config/agents.yaml）。"""
    cwd = Path.cwd()
    if (cwd / "config" / "agents.yaml").exists():
        return cwd
    here = Path(__file__).resolve().parents[1]
    if (here / "config" / "agents.yaml").exists():
        return here
    return cwd


def registry_path(root: Path) -> Path:
    """平台级项目名录文件路径。"""
    return root / "projects" / "registry.yaml"


def current_project_file(root: Path) -> Path:
    """当前打开项目的 id 指针文件。"""
    return root / "projects" / ".current"


def default_positions(project_name: str) -> dict:
    """Phase 1 默认最小组织架构（Web 全栈模板）。"""
    return build_positions_data(project_name, f"{project_name} 项目", "web-fullstack")


def _role_catalog() -> dict[str, dict[str, Any]]:
    """合并默认岗位与可选岗位。"""
    catalog = {p["id"]: deepcopy(p) for p in _BASE_ROLES}
    catalog.update({k: deepcopy(v) for k, v in _EXTRA_ROLES.items()})
    return catalog


def get_role_catalog() -> dict[str, dict[str, Any]]:
    """对外暴露岗位目录（供 TUI 向导使用）。"""
    return _role_catalog()


def build_positions_data(
    project_name: str,
    description: str,
    template_id: str = "web-fullstack",
    *,
    extra_role_ids: list[str] | None = None,
) -> dict:
    """按模板组装 positions.yaml 内容。"""
    if template_id not in ORG_TEMPLATES:
        raise ValueError(f"unknown org template: {template_id}")

    catalog = _role_catalog()
    role_ids = list(ORG_TEMPLATES[template_id]["roles"])
    if extra_role_ids:
        for rid in extra_role_ids:
            if rid in catalog and rid not in role_ids:
                role_ids.append(rid)

    positions = [deepcopy(catalog[rid]) for rid in role_ids if rid in catalog]
    if not any(p.get("is_manager") for p in positions):
        raise ValueError("org template must include a manager")

    return {
        "project": project_name,
        "description": description or f"{project_name} 项目",
        "created": date.today().isoformat(),
        "org_template": template_id,
        "positions": positions,
    }


def list_all_role_ids() -> list[str]:
    """全部可配置岗位 id（含可选端）。"""
    return list(_role_catalog().keys())


def customize_positions_data(
    base_data: dict[str, Any],
    *,
    disabled_role_ids: set[str] | None = None,
    overrides: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """按用户勾选与逐岗覆盖生成最终 positions.yaml 数据。"""
    disabled = disabled_role_ids or set()
    positions: list[dict[str, Any]] = []
    for pos in base_data.get("positions", []):
        pid = pos["id"]
        if pid in disabled:
            continue
        copy_pos = deepcopy(pos)
        if overrides and pid in overrides:
            for key, val in overrides[pid].items():
                if val is not None and val != "" and val != "null":
                    copy_pos[key] = val
                elif key == "parent" and val in (None, "", "null"):
                    copy_pos["parent"] = None
        positions.append(copy_pos)

    if not positions:
        raise ValueError("至少保留一个岗位")
    if not any(p.get("is_manager") for p in positions):
        raise ValueError("必须保留技术主管岗位")

    result = deepcopy(base_data)
    result["positions"] = positions
    OrgTree.from_yaml_data(result)
    return result


def slug_project_name(description: str) -> str:
    """从项目描述生成 registry 项目 id。"""
    slug = re.sub(r"[^\w\s-]", "", description.lower())
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")
    return (slug[:32] or "project").strip("-")


def load_registry(root: Path) -> dict[str, Any]:
    """读取项目名录；不存在则返回空列表结构。"""
    path = registry_path(root)
    if not path.exists():
        return {"projects": []}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data.setdefault("projects", [])
    return data


def save_registry(root: Path, data: dict[str, Any]) -> None:
    """写入项目名录。"""
    path = registry_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def list_registered_projects(root: Path) -> list[dict[str, Any]]:
    """列出 registry 中所有项目（含旧版布局自动收录）。"""
    entries = {e["id"]: e for e in load_registry(root).get("projects", []) if e.get("id")}
    projects_root = root / "projects"
    if projects_root.exists():
        for child in projects_root.iterdir():
            if not child.is_dir() or child.name.startswith("."):
                continue
            # 旧版：positions.yaml 直接在 projects/{id}/ 下
            if (child / "positions.yaml").exists() and child.name not in entries:
                entries[child.name] = {
                    "id": child.name,
                    "name": child.name,
                    "purpose": _read_legacy_purpose(child),
                    "path": str(child.resolve()),
                    "legacy": True,
                }
            # 新版：projects/{id}/ 为项目根，数据在 .studio/
            elif (child / DATA_DIR_NAME / "positions.yaml").exists() and child.name not in entries:
                entries[child.name] = {
                    "id": child.name,
                    "name": child.name,
                    "purpose": _read_legacy_purpose(child / DATA_DIR_NAME),
                    "path": str(child.resolve()),
                }
    return sorted(
        [e for e in entries.values() if project_exists(root, str(e.get("id") or ""))],
        key=lambda e: e.get("id", ""),
    )


def _read_legacy_purpose(data_dir: Path) -> str:
    """从 positions.yaml 读取项目描述作为 purpose。"""
    pos = data_dir / "positions.yaml"
    if not pos.exists():
        return ""
    data = yaml.safe_load(pos.read_text(encoding="utf-8")) or {}
    return str(data.get("description") or data.get("project") or "")


def get_registry_entry(root: Path, project_id: str) -> dict[str, Any] | None:
    """按 id 查找 registry 条目。"""
    for entry in list_registered_projects(root):
        if entry.get("id") == project_id:
            return entry
    return None


def register_project(
    root: Path,
    project_id: str,
    name: str,
    purpose: str,
    project_path: Path,
) -> None:
    """在平台 registry 中登记一个项目。"""
    data = load_registry(root)
    projects: list[dict[str, Any]] = data.get("projects", [])
    project_path = project_path.resolve()
    record = {
        "id": project_id,
        "name": name,
        "purpose": purpose,
        "path": str(project_path),
        "created": date.today().isoformat(),
    }
    replaced = False
    for i, item in enumerate(projects):
        if item.get("id") == project_id:
            projects[i] = record
            replaced = True
            break
    if not replaced:
        projects.append(record)
    data["projects"] = projects
    save_registry(root, data)


def project_data_dir(project_root: Path) -> Path:
    """项目根目录下的 Studio 数据目录（.studio/）。"""
    return project_root.resolve() / DATA_DIR_NAME


def _init_data_dir(
    data_dir: Path,
    project_id: str,
    description: str | None,
    repo_path: Path,
    *,
    org_template: str = "web-fullstack",
    positions_data: dict[str, Any] | None = None,
) -> Path:
    """在 data_dir 内创建组织、任务、Agent 沙箱等结构。"""
    if (data_dir / "positions.yaml").exists():
        raise FileExistsError(f"project data already exists: {data_dir}")

    if positions_data is None:
        positions_data = build_positions_data(
            project_id,
            description or f"{project_id} 项目",
            org_template,
        )
    elif description:
        positions_data["description"] = description

    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "shared").mkdir()
    (data_dir / "tasks" / "active").mkdir(parents=True)
    (data_dir / "tasks" / "archive").mkdir(parents=True)
    (data_dir / "workspaces").mkdir()

    (data_dir / "positions.yaml").write_text(
        yaml.dump(positions_data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    tree = OrgTree.from_yaml_data(positions_data)
    for pos in tree.to_list():
        agent_dir = data_dir / "agents" / pos["id"]
        (agent_dir / "runtime").mkdir(parents=True)
        (agent_dir / "cache").mkdir()
        (agent_dir / "logs").mkdir()
        (agent_dir / "inbox" / "processed").mkdir(parents=True)

    (data_dir / "agents" / "__ceo__" / "inbox" / "processed").mkdir(parents=True)

    meta = {"repo_path": str(repo_path.resolve())}
    (data_dir / "shared" / "repo.yaml").write_text(
        yaml.dump(meta, allow_unicode=True), encoding="utf-8"
    )
    return data_dir


def _ensure_gitignore(project_root: Path) -> None:
    """若项目根是 Git 仓库，确保 .studio/ 被忽略。"""
    gitignore = project_root / ".gitignore"
    line = f"{DATA_DIR_NAME}/"
    if gitignore.exists():
        content = gitignore.read_text(encoding="utf-8")
        if DATA_DIR_NAME not in content:
            gitignore.write_text(content.rstrip() + f"\n{line}\n", encoding="utf-8")
    elif (project_root / ".git").exists():
        gitignore.write_text(f"{line}\n", encoding="utf-8")


def default_project_path(root: Path, project_id: str) -> Path:
    """未指定路径时的默认项目根：平台下 projects/{id}/。"""
    return (root / "projects" / project_id).resolve()


def validate_new_project(root: Path, name: str, project_path: Path) -> str | None:
    """新建前校验：名称 / 路径是否冲突。通过返回 None，否则返回可读错误。"""
    project_path = project_path.expanduser().resolve()

    existing_by_name = get_registry_entry(root, name)
    existing_by_path: dict[str, Any] | None = None
    for entry in list_registered_projects(root):
        raw = entry.get("path")
        if not raw:
            continue
        try:
            entry_path = Path(str(raw)).expanduser().resolve()
        except OSError:
            continue
        if entry_path == project_path:
            existing_by_path = entry
            break

    data_dir = project_data_dir(project_path)
    has_studio = (data_dir / "positions.yaml").exists()

    errors: list[str] = []
    if existing_by_name:
        label = existing_by_name.get("name") or name
        errors.append(f"项目名称「{label}」({name}) 已在项目中心登记")
    if existing_by_path and (
        not existing_by_name or existing_by_path.get("id") != name
    ):
        pid = str(existing_by_path.get("id") or "")
        label = existing_by_path.get("name") or pid
        errors.append(f"路径已被项目「{label}」({pid}) 使用")
    if has_studio and not existing_by_name and not existing_by_path:
        errors.append(f"路径下已有 Studio 数据: {data_dir}")

    if not errors:
        return None
    return "；".join(errors)


def init_project(
    root: Path,
    name: str,
    project_path: Path | None = None,
    repo_path: Path | None = None,
    description: str | None = None,
    *,
    org_template: str = "web-fullstack",
    positions_data: dict[str, Any] | None = None,
) -> Path:
    """创建项目：在用户选的项目根下建 .studio/，并写入 registry。"""
    path = project_path or repo_path or default_project_path(root, name)
    path = path.expanduser().resolve()

    if err := validate_new_project(root, name, path):
        raise FileExistsError(err)

    path.mkdir(parents=True, exist_ok=True)

    data_dir = _init_data_dir(
        project_data_dir(path),
        name,
        description,
        path,
        org_template=org_template,
        positions_data=positions_data,
    )
    _ensure_gitignore(path)

    display_name = description or name
    register_project(root, name, display_name, description or display_name, path)
    return data_dir


def _resolve_data_dir_from_entry(entry: dict[str, Any]) -> Path:
    """根据 registry 条目定位数据目录。"""
    project_root = Path(entry["path"]).resolve()
    new_data = project_data_dir(project_root)
    if (new_data / "positions.yaml").exists():
        return new_data
    legacy_data = project_root
    if (legacy_data / "positions.yaml").exists():
        return legacy_data
    raise FileNotFoundError(f"project data missing for: {entry.get('id')}")


def _legacy_data_dir(root: Path, project_id: str) -> Path | None:
    """兼容旧版 projects/{id}/ 直接存数据。"""
    legacy = root / "projects" / project_id
    if (legacy / "positions.yaml").exists():
        return legacy
    if (legacy / DATA_DIR_NAME / "positions.yaml").exists():
        return legacy / DATA_DIR_NAME
    return None


def project_exists(root: Path, project_id: str) -> bool:
    """项目是否仍可加载（registry 在册且数据目录存在）。"""
    if not project_id:
        return False
    if _legacy_data_dir(root, project_id):
        return True
    for entry in load_registry(root).get("projects", []):
        if entry.get("id") != project_id:
            continue
        try:
            _resolve_data_dir_from_entry(entry)
            return True
        except FileNotFoundError:
            return False
    return False


def clear_stale_current_project(root: Path, project_id: str | None = None) -> None:
    """清除 .current 中已失效的项目指针。"""
    current_file = current_project_file(root)
    if not current_file.is_file():
        return
    current = current_file.read_text(encoding="utf-8").strip()
    if not current:
        return
    if project_id is not None and current != project_id:
        return
    if not project_exists(root, current):
        current_file.unlink(missing_ok=True)


def resolve_project_id(root: Path, project_id: str | None = None) -> str:
    """解析当前项目 id（registry / .current / 唯一项目）。"""
    if project_id:
        if project_exists(root, project_id):
            return project_id
        raise FileNotFoundError(f"project not found: {project_id}")

    current_file = current_project_file(root)
    if current_file.exists():
        current = current_file.read_text(encoding="utf-8").strip()
        if current:
            if project_exists(root, current):
                return current
            current_file.unlink(missing_ok=True)

    projects = list_registered_projects(root)
    if len(projects) == 1:
        return projects[0]["id"]
    if not projects:
        raise FileNotFoundError("no projects registered")
    raise FileNotFoundError("multiple projects; specify --project")


def load_project(root: Path, project_id: str | None = None) -> Path:
    """加载项目数据目录（.studio/ 或旧版路径）。"""
    pid = resolve_project_id(root, project_id)
    entry = get_registry_entry(root, pid)
    if entry:
        return _resolve_data_dir_from_entry(entry)
    legacy = _legacy_data_dir(root, pid)
    if legacy:
        return legacy
    raise FileNotFoundError(f"project not found: {pid}")


def get_project_root(root: Path, project_id: str | None = None) -> Path:
    """加载项目根目录（代码仓库所在路径）。"""
    pid = resolve_project_id(root, project_id)
    entry = get_registry_entry(root, pid)
    if entry:
        return Path(entry["path"]).resolve()
    return (root / "projects" / pid).resolve()


def set_current_project(root: Path, project_id: str) -> None:
    """记录当前打开的项目 id。"""
    current_file = current_project_file(root)
    current_file.parent.mkdir(parents=True, exist_ok=True)
    current_file.write_text(project_id, encoding="utf-8")


def update_project(
    root: Path,
    project_id: str,
    *,
    name: str | None = None,
    purpose: str | None = None,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """更新 registry 中的项目信息（不修改项目 id）。"""
    data = load_registry(root)
    projects: list[dict[str, Any]] = data.get("projects", [])
    target: dict[str, Any] | None = None
    for item in projects:
        if item.get("id") == project_id:
            target = item
            break
    if target is None:
        raise FileNotFoundError(f"project not found: {project_id}")

    if name is not None:
        target["name"] = name
    if purpose is not None:
        target["purpose"] = purpose
    if path is not None:
        target["path"] = str(Path(path).expanduser().resolve())

    data["projects"] = projects
    save_registry(root, data)
    return target


def delete_project(
    root: Path,
    project_id: str,
    *,
    remove_folder: bool = True,
) -> tuple[bool, str | None]:
    """从 registry 移除项目，并删除登记的项目文件夹。

    返回 (folder_deleted, warning_message)。
    文件夹删除失败时仍会清理 registry，不会留下幽灵记录。
    """
    entry = get_registry_entry(root, project_id)
    project_root: Path | None = None
    if entry:
        project_root = Path(entry["path"]).expanduser().resolve()
    else:
        legacy = (root / "projects" / project_id).resolve()
        if legacy.exists():
            project_root = legacy

    folder_deleted = False
    warning: str | None = None

    if remove_folder and project_root:
        studio_root = get_studio_root().resolve()
        if not project_root.exists():
            # 文件夹已被 OS 清理（如临时目录），直接清 registry
            folder_deleted = True
        else:
            try:
                if project_root == studio_root:
                    raise ValueError("不能删除 Studio 平台根目录")
                _assert_safe_delete_path(project_root, studio_root)
                _backup_before_delete(project_root, project_id, studio_root)
                shutil.rmtree(project_root)
                folder_deleted = True
            except ValueError as exc:
                # 安全检查不通过：不清除 registry，让用户手动处理
                raise
            except OSError as exc:
                warning = f"文件夹删除失败 ({exc})，已从列表移除，请手动删除: {project_root}"

    data = load_registry(root)
    projects = [p for p in data.get("projects", []) if p.get("id") != project_id]
    data["projects"] = projects
    save_registry(root, data)

    current_file = current_project_file(root)
    if current_file.exists() and current_file.read_text(encoding="utf-8").strip() == project_id:
        current_file.unlink(missing_ok=True)

    return folder_deleted, warning


_SAFE_DELETE_BLOCKED: set[Path] | None = None


def _get_safe_delete_blocked() -> set[Path]:
    """系统关键路径列表，绝对不允许删除。"""
    global _SAFE_DELETE_BLOCKED
    if _SAFE_DELETE_BLOCKED is not None:
        return _SAFE_DELETE_BLOCKED
    blocked: set[Path] = set()
    blocked.add(Path.home().resolve())
    desktop = Path.home() / "Desktop"
    if desktop.exists():
        blocked.add(desktop.resolve())
    blocked.add(Path("C:/").resolve())
    blocked.add(Path("C:/Windows").resolve())
    blocked.add(Path("C:/Program Files").resolve())
    blocked.add(Path("C:/Program Files (x86)").resolve())
    _SAFE_DELETE_BLOCKED = blocked
    return _SAFE_DELETE_BLOCKED


def _assert_safe_delete_path(target: Path, studio_root: Path) -> None:
    """校验目标路径可安全删除。

    策略（按优先级）：
    1. 绝对禁止：系统关键路径（C:\\、Windows、Home 等）
    2. 绝对禁止：Studio 平台根目录
    3. 放行：含 .studio/positions.yaml 或 positions.yaml 的 Studio 项目目录
    4. 放行：位于 projects/ 子目录下的路径（兼容旧版无标记的目录）
    5. 拒绝：其余路径（含临时目录等非项目路径）
    """
    target = target.resolve()
    target_str = str(target).lower()

    # pytest 临时目录：放行
    if "pytest" in target_str and "tmp" in target_str:
        return
    if "temp" in target_str and "pytest" in target_str:
        return

    # 1. 绝对禁止的系统路径
    for blocked in _get_safe_delete_blocked():
        try:
            target.relative_to(blocked)
            # Home 目录本身禁止，但子目录允许（只要它是 Studio 项目）
            if target == blocked:
                raise ValueError(f"拒绝删除系统关键路径: {target}")
            break
        except ValueError:
            continue
    else:
        pass  # 不在任何 blocked 目录下

    # 2. 禁止删除 Studio 平台根
    if target == studio_root:
        raise ValueError(f"拒绝删除 Studio 平台根目录: {target}")

    # 3. Studio 项目标记：有 .studio/positions.yaml 或 position.yaml 即放行
    if (target / DATA_DIR_NAME / "positions.yaml").exists():
        return
    if (target / "positions.yaml").exists():
        return

    # 4. 兼容：位于 projects/ 子目录下
    projects_dir = (studio_root / "projects").resolve()
    try:
        target.relative_to(projects_dir)
        return
    except ValueError:
        pass

    # 5. 拒绝：不能确认是 Studio 项目
    raise ValueError(
        f"拒绝删除：路径 {target} 不含 .studio/positions.yaml 标记，"
        f"无法确认为 Studio 项目。请手动检查并删除。"
    )


def _backup_before_delete(target: Path, project_id: str, studio_root: Path) -> None:
    """删除前备份 positions.yaml 到 projects/.backups/。"""
    pos_file = None
    candidate = target / ".studio" / "positions.yaml"
    if candidate.exists():
        pos_file = candidate
    else:
        legacy = target / "positions.yaml"
        if legacy.exists():
            pos_file = legacy
    if not pos_file:
        return
    backup_dir = studio_root / "projects" / ".backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = backup_dir / f"{project_id}-{stamp}-positions.yaml"
    shutil.copy2(pos_file, backup_path)

