from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_required_directories_exist():
    dirs = [
        "config",
        "core",
        "agents",
        "cli",
        "supervisor",
        "platform/memory",
        "platform/skills",
        "platform/mcp",
        "docs/superpowers/specs",
        "docs/superpowers/plans",
    ]
    for d in dirs:
        assert (ROOT / d).is_dir(), f"missing directory: {d}"


def test_config_files_exist():
    assert (ROOT / "config" / "agents.yaml").is_file()
    assert (ROOT / "config" / "models.yaml").is_file()
