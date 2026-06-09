from pathlib import Path

import yaml

from core.org.tree_ops import OrgTree
from core.platform.mcp_client import McpGateway, load_mcp_registry, resolve_mcp_for_position
from core.platform.skills_client import prepare_worker_runtime
from core.project import init_project
from core.rbac.permission import effective_mcp_use, effective_skill_use


def _setup_platform(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "agents.yaml").write_text(
        "agents:\n  hermes:\n    command: echo\n    flags: ''\n", encoding="utf-8"
    )
    (tmp_path / "platform" / "skills" / "packages" / "fastapi-expert").mkdir(parents=True)
    (tmp_path / "platform" / "skills" / "registry.yaml").write_text(
        "skills:\n  - id: fastapi-expert\n    name: FastAPI\n    package: packages/fastapi-expert\n",
        encoding="utf-8",
    )
    (tmp_path / "platform" / "mcp").mkdir(parents=True, exist_ok=True)
    (tmp_path / "platform" / "mcp" / "registry.yaml").write_text(
        "servers:\n  - id: postgres-mcp\n    name: PG\n    transport: stdio\n",
        encoding="utf-8",
    )


def test_effective_skill_use_respects_resume(tmp_path: Path):
    _setup_platform(tmp_path)
    init_project(tmp_path, "demo", project_path=tmp_path / "proj", description="t")
    data = yaml.safe_load(
        (tmp_path / "proj" / ".studio" / "positions.yaml").read_text(encoding="utf-8")
    )
    tree = OrgTree.from_yaml_data(data)
    dazhuang = next(p for p in data["positions"] if p["id"] == "dazhuang")
    allowed = effective_skill_use(tree, dazhuang, {"fastapi-expert", "vue-debug"})
    assert "fastapi-expert" in allowed
    assert "vue-debug" not in allowed


def test_resolve_mcp_for_worker(tmp_path: Path):
    _setup_platform(tmp_path)
    init_project(tmp_path, "demo", project_path=tmp_path / "proj", description="t")
    data = yaml.safe_load(
        (tmp_path / "proj" / ".studio" / "positions.yaml").read_text(encoding="utf-8")
    )
    tree = OrgTree.from_yaml_data(data)
    dazhuang = next(p for p in data["positions"] if p["id"] == "dazhuang")
    mcp = resolve_mcp_for_position(tmp_path, dazhuang, tree=tree)
    assert mcp == ["postgres-mcp"]


def test_mcp_gateway_allowlist(tmp_path: Path):
    _setup_platform(tmp_path)
    init_project(tmp_path, "demo", project_path=tmp_path / "proj", description="t")
    project_dir = tmp_path / "proj" / ".studio"
    data = yaml.safe_load((project_dir / "positions.yaml").read_text(encoding="utf-8"))
    dazhuang = next(p for p in data["positions"] if p["id"] == "dazhuang")
    prepare_worker_runtime(tmp_path, project_dir, "dazhuang", dazhuang)
    gw = McpGateway(tmp_path, project_dir, "dazhuang")
    result = gw.invoke("postgres-mcp", "query", {"sql": "select 1"})
    assert result["ok"] is True
    audit = project_dir / "agents" / "dazhuang" / "logs" / "mcp-audit.log"
    assert audit.exists()


def test_mcp_gateway_denies_unknown(tmp_path: Path):
    _setup_platform(tmp_path)
    init_project(tmp_path, "demo", project_path=tmp_path / "proj", description="t")
    project_dir = tmp_path / "proj" / ".studio"
    data = yaml.safe_load((project_dir / "positions.yaml").read_text(encoding="utf-8"))
    dazhuang = next(p for p in data["positions"] if p["id"] == "dazhuang")
    prepare_worker_runtime(tmp_path, project_dir, "dazhuang", dazhuang)
    gw = McpGateway(tmp_path, project_dir, "dazhuang")
    try:
        gw.invoke("filesystem-mcp", "read", {})
        assert False, "should raise"
    except Exception:
        pass


def test_load_mcp_registry(tmp_path: Path):
    _setup_platform(tmp_path)
    reg = load_mcp_registry(tmp_path)
    assert "postgres-mcp" in reg
