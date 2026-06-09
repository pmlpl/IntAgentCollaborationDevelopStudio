from pathlib import Path

import yaml

from cli.studio import main
from core.org.expand_ops import expand_add_role, expand_business_line, list_missing_roles
from core.org.persist import load_positions_data
from core.org.tree_ops import OrgTree
from core.project import init_project


def _setup(tmp_path: Path) -> Path:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "agents.yaml").write_text("agents: {}\n", encoding="utf-8")
    init_project(tmp_path, "demo", project_path=tmp_path / "proj", description="Web 项目")
    return tmp_path / "proj" / ".studio"


def test_list_missing_roles_miniprogram(tmp_path: Path):
    project_dir = _setup(tmp_path)
    data = load_positions_data(project_dir)
    missing = list_missing_roles(data, "web-miniprogram")
    assert "xiaocheng" in missing


def test_expand_business_adds_role(tmp_path: Path):
    project_dir = _setup(tmp_path)
    _, added = expand_business_line(
        project_dir,
        "开发微信小程序",
        template_id="web-miniprogram",
        role_ids=["xiaocheng"],
    )
    assert "xiaocheng" in added
    data = load_positions_data(project_dir)
    ids = {p["id"] for p in data["positions"]}
    assert "xiaocheng" in ids
    assert (project_dir / "agents" / "xiaocheng" / "inbox").exists()


def test_expand_add_role(tmp_path: Path):
    project_dir = _setup(tmp_path)
    expand_add_role(project_dir, "xiaomo", parent_id="laowang")
    data = load_positions_data(project_dir)
    xiaomo = next(p for p in data["positions"] if p["id"] == "xiaomo")
    assert xiaomo["parent"] == "laowang"


def test_org_remove_reassign(tmp_path: Path):
    project_dir = _setup(tmp_path)
    expand_add_role(project_dir, "xiaomo", parent_id="laowang")
    data = load_positions_data(project_dir)
    tree = OrgTree.from_yaml_data(data)
    tree.remove_node("xiaomo", strategy="archive")
    assert "xiaomo" not in {p["id"] for p in tree.to_list()}


def test_studio_org_show(tmp_path: Path, monkeypatch):
    project_dir = _setup(tmp_path)
    monkeypatch.chdir(tmp_path)
    rc = main(["org", "show", "--project", "demo"])
    assert rc == 0


def test_studio_expand_business_dry_run(tmp_path: Path, monkeypatch):
    project_dir = _setup(tmp_path)
    monkeypatch.chdir(tmp_path)
    rc = main(["expand", "business", "微信小程序", "--project", "demo"])
    assert rc == 1


def test_studio_expand_business_yes(tmp_path: Path, monkeypatch):
    project_dir = _setup(tmp_path)
    monkeypatch.chdir(tmp_path)
    rc = main(["expand", "business", "微信小程序", "--project", "demo", "--yes"])
    assert rc == 0
    data = yaml.safe_load((project_dir / "positions.yaml").read_text(encoding="utf-8"))
    assert any(p["id"] == "xiaocheng" for p in data["positions"])
