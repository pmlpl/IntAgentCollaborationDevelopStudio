# core/org/tree_ops.py — 组织树 CRUD 与环检测
from __future__ import annotations

from copy import deepcopy
from typing import Any


class OrgTreeError(Exception):
    """组织树操作异常。"""


class OrgTree:
    """基于 parent 引用的组织树。"""

    def __init__(self, positions: list[dict[str, Any]]):
        self._positions = {p["id"]: deepcopy(p) for p in positions}
        self._validate()

    def _validate(self) -> None:
        for pid, pos in self._positions.items():
            parent = pos.get("parent")
            if parent is not None and parent not in self._positions:
                raise OrgTreeError(f"unknown parent {parent!r} for {pid!r}")
        if self._has_cycle():
            raise OrgTreeError("cycle detected in org tree")

    def _has_cycle(self) -> bool:
        for pid in self._positions:
            seen: set[str] = set()
            cur: str | None = pid
            while cur is not None:
                if cur in seen:
                    return True
                seen.add(cur)
                cur = self._positions[cur].get("parent")
        return False

    def subtree(self, node_id: str) -> list[str]:
        if node_id not in self._positions:
            raise OrgTreeError(f"unknown node {node_id!r}")
        result = [node_id]
        for pid in self._positions:
            if pid != node_id and self._is_descendant(pid, node_id):
                result.append(pid)
        return result

    def _is_descendant(self, node_id: str, ancestor_id: str) -> bool:
        cur = self._positions[node_id].get("parent")
        while cur is not None:
            if cur == ancestor_id:
                return True
            cur = self._positions[cur].get("parent")
        return False

    def ancestors(self, node_id: str) -> list[str]:
        if node_id not in self._positions:
            raise OrgTreeError(f"unknown node {node_id!r}")
        chain: list[str] = []
        cur = self._positions[node_id].get("parent")
        while cur is not None:
            chain.append(cur)
            cur = self._positions[cur].get("parent")
        return chain

    def add_node(self, parent_id: str, spec: dict[str, Any]) -> None:
        if parent_id not in self._positions:
            raise OrgTreeError(f"unknown parent {parent_id!r}")
        nid = spec["id"]
        if nid in self._positions:
            raise OrgTreeError(f"duplicate id {nid!r}")
        spec = deepcopy(spec)
        spec["parent"] = parent_id
        self._positions[nid] = spec
        self._validate()

    def move_subtree(self, node_id: str, new_parent_id: str) -> None:
        if node_id not in self._positions:
            raise OrgTreeError(f"unknown node {node_id!r}")
        if new_parent_id not in self._positions:
            raise OrgTreeError(f"unknown parent {new_parent_id!r}")
        if new_parent_id in self.subtree(node_id):
            raise OrgTreeError("cycle: cannot move node under its descendant")
        self._positions[node_id]["parent"] = new_parent_id
        self._validate()

    def root_managers(self) -> list[str]:
        """返回 parent 为 null 且 is_manager 为 true 的节点 id。"""
        return [
            pid
            for pid, pos in self._positions.items()
            if pos.get("parent") is None and pos.get("is_manager")
        ]

    def to_list(self) -> list[dict[str, Any]]:
        return list(self._positions.values())

    @classmethod
    def from_yaml_data(cls, data: dict) -> OrgTree:
        return cls(data.get("positions", []))
