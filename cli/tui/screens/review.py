# cli/tui/screens/review.py — CEO 审批（Phase 1.5：列表 + 通过/打回）
from __future__ import annotations

import yaml

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Label, ListItem, ListView, Static

from core.dispatch.dispatcher import get_dispatcher
from core.dispatch.review_compliance import build_review_checklist, format_review_checklist
from core.org.tree_ops import OrgTree
from core.project import get_studio_root, load_project, resolve_project_id


class ReviewScreen(Screen):
    """待审批任务：选择任务后通过或打回。"""

    BINDINGS = [
        ("escape", "back", "返回"),
        ("a", "approve", "通过"),
        ("x", "reject", "打回"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._pending: list[dict] = []
        self._checklist_cache: dict[str, str] = {}  # task_id → 渲染后 checklist

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Vertical(
            Static("[bold]CEO 审批[/]", classes="title-text"),
            Static("[dim]↑↓ 选中 · A 通过 · X 打回 · Esc 返回[/]", classes="page-hint"),
            ListView(id="review-list"),
            Static("", id="review-checklist", classes="panel-box muted"),
            id="review-box",
            classes="page-shell page-body",
        )
        yield Footer()

    def on_mount(self) -> None:
        self._load()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id == "review-list":
            self._update_checklist()

    def _update_checklist(self) -> None:
        """更新右侧审查清单（结果缓存，避免每次光标移动重读文件）。

        旧实现在 on_list_view_highlighted 中每次都 yaml.safe_load +
        OrgTree.from_yaml_data + build_review_checklist，导致切换卡顿。
        """
        widget = self.query_one("#review-checklist", Static)
        task = self._selected_task()
        if not task:
            widget.update("")
            return
        task_id = task.get("id", "")
        cached = self._checklist_cache.get(task_id)
        if cached is not None:
            widget.update(cached)
            return

        root = get_studio_root()
        project_id = getattr(self.app, "project_name", None) or resolve_project_id(root)
        try:
            project_dir = load_project(root, project_id)
            data = yaml.safe_load(
                (project_dir / "positions.yaml").read_text(encoding="utf-8")
            )
            tree = OrgTree.from_yaml_data(data)
            assignee_id = task.get("assignee") or ""
            assignee = next(
                (p for p in data.get("positions", []) if p.get("id") == assignee_id),
                {"id": assignee_id, "resume": {}},
            )
            lines = build_review_checklist(root, tree, task, assignee)
            text = format_review_checklist(lines)
            self._checklist_cache[task_id] = text
            widget.update(text)
        except FileNotFoundError:
            widget.update("")

    def _load(self) -> None:
        root = get_studio_root()
        list_view = self.query_one("#review-list", ListView)
        list_view.clear()
        self._pending = []
        self._checklist_cache.clear()
        try:
            project_id = getattr(self.app, "project_name", None) or resolve_project_id(root)
            disp = get_dispatcher(root, project_id)
        except FileNotFoundError:
            list_view.append(ListItem(Label("[dim]无项目[/]")))
            return
        self._pending = disp.get_pending_reviews()
        if not self._pending:
            list_view.append(ListItem(Label("[dim]暂无待审批项[/]")))
            return
        for t in self._pending:
            list_view.append(
                ListItem(
                    Label(
                        f"{t['id']} — {t.get('description', '')[:60]}\n"
                        f"状态: {t.get('status')}"
                    )
                )
            )
        self._update_checklist()

    def _selected_task(self) -> dict | None:
        if not self._pending:
            return None
        idx = self.query_one("#review-list", ListView).index
        if idx is None or idx >= len(self._pending):
            return self._pending[0]
        return self._pending[idx]

    def _submit(self, verdict: str) -> None:
        task = self._selected_task()
        if not task:
            return
        root = get_studio_root()
        project_id = getattr(self.app, "project_name", None) or resolve_project_id(root)
        disp = get_dispatcher(root, project_id)
        disp.submit_review(task["id"], verdict)
        self._load()

    def action_approve(self) -> None:
        self._submit("approved")

    def action_reject(self) -> None:
        self._submit("rejected")

    def action_back(self) -> None:
        self.app.pop_screen()
