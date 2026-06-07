import pytest

from core.org.tree_ops import OrgTree, OrgTreeError

SAMPLE = [
    {"id": "laowang", "name": "老王", "parent": None, "is_manager": True},
    {"id": "xiaohong", "name": "小红", "parent": "laowang"},
    {"id": "dazhuang", "name": "大壮", "parent": "laowang"},
]


def test_subtree_returns_descendants():
    tree = OrgTree(SAMPLE)
    assert set(tree.subtree("laowang")) == {"laowang", "xiaohong", "dazhuang"}


def test_subtree_leaf_is_self_only():
    tree = OrgTree(SAMPLE)
    assert tree.subtree("xiaohong") == ["xiaohong"]


def test_move_subtree_rejects_cycle():
    tree = OrgTree(SAMPLE)
    with pytest.raises(OrgTreeError, match="cycle"):
        tree.move_subtree("laowang", "xiaohong")


def test_add_node_under_parent():
    tree = OrgTree(SAMPLE)
    tree.add_node("laowang", {"id": "xiaoyan", "name": "小严", "parent": "laowang"})
    assert "xiaoyan" in tree.subtree("laowang")


def test_ancestors():
    tree = OrgTree(SAMPLE)
    assert tree.ancestors("xiaohong") == ["laowang"]
