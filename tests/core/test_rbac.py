from core.org.tree_ops import OrgTree
from core.rbac.inherit import collect_domain_grants


def test_collect_domain_grants_from_ancestor():
    positions = [
        {
            "id": "laowang",
            "parent": None,
            "permissions": {"skills": {"use": ["fastapi-expert"]}},
        },
        {"id": "dazhuang", "parent": "laowang", "resume": {"skills": ["python-async"]}},
    ]
    tree = OrgTree(positions)
    grants = collect_domain_grants(tree, "dazhuang", "skills", "use")
    assert "fastapi-expert" in grants
