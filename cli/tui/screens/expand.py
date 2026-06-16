# cli/tui/screens/expand.py — 扩建公司向导（统一全屏布局）
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Checkbox, Footer, Header, Input, Select, Static

from core.org.expand_ops import (
    expand_add_role,
    expand_business_line,
    expand_insert_manager,
    list_missing_roles,
)
from core.org.persist import load_positions_data
from core.org.tree_ops import OrgTreeError
from core.project import get_role_catalog, get_studio_root, load_project
from core.research.expand import mock_expand_research


class ExpandScreen(Screen):
    """扩建向导：新业务线 / 加管理层 / 部门内加人。"""

    BINDINGS = [
        ("escape", "back", "返回"),
        ("ctrl+enter", "primary_action", "继续"),
    ]

    def __init__(self, project_name: str | None = None) -> None:
        super().__init__()
        self.project_name = project_name
        self._mode = ""
        self._panel = "mode"
        self._description = ""
        self._research_text = ""
        self._roles_to_add: list[str] = []
        self._template_id = ""
        self._positions: list[dict] = []
        self._manager_children: list[str] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Container(
            VerticalScroll(
                Static("[bold]扩建公司[/]", classes="title-text"),
                Static("", id="expand-step-indicator", classes="muted"),
                Static("", id="expand-status", classes="muted"),
                Vertical(
                    Static("选择扩建类型", classes="accent"),
                    Select(
                        [
                            ("开新业务线（调研 + 加岗位）", "business"),
                            ("加管理层（插入主管）", "manager"),
                            ("部门内加人", "role"),
                        ],
                        id="expand-mode",
                    ),
                    id="panel-mode",
                    classes="page-step",
                ),
                Vertical(
                    Static("新业务描述", classes="accent"),
                    Input(placeholder="例如：开发微信小程序", id="business-desc"),
                    id="panel-business-1",
                    classes="page-step",
                ),
                Vertical(
                    VerticalScroll(
                        Static("", id="business-research", classes="panel-box"),
                        Static("", id="business-roles-preview"),
                        id="business-research-scroll",
                        classes="page-scroll",
                    ),
                    id="panel-business-2",
                    classes="page-step",
                ),
                Vertical(
                    Static("选择岗位与上级", classes="accent"),
                    Select([], id="role-pick"),
                    Select([], id="role-parent"),
                    id="panel-role",
                    classes="page-step",
                ),
                Vertical(
                    Static("选择改由新主管管理的下属（勾选）", classes="accent"),
                    VerticalScroll(id="manager-children-box", classes="page-scroll"),
                    Input(placeholder="新主管 id（英文，如 frontend-lead）", id="manager-id"),
                    Input(placeholder="花名（如 前端组长）", id="manager-name"),
                    Select([], id="manager-reports-to"),
                    id="panel-manager",
                    classes="page-step",
                ),
                classes="page-body",
            ),
            Static("", id="page-hint", classes="page-hint"),
            Horizontal(
                Button("继续", variant="primary", id="btn-primary"),
                classes="page-actions",
            ),
            id="expand-container",
            classes="page-shell",
        )
        yield Footer()

    def on_mount(self) -> None:
        self._load_positions()
        self._show_panel("mode")

    def _project_dir(self):
        root = get_studio_root()
        pid = self.project_name or getattr(self.app, "project_name", None)
        return root, load_project(root, pid), pid

    def _load_positions(self) -> None:
        _, project_dir, _ = self._project_dir()
        data = load_positions_data(project_dir)
        self._positions = list(data.get("positions") or [])

    def _set_status(self, message: str, *, error: bool = False) -> None:
        prefix = "[red]" if error else "[dim]"
        self.query_one("#expand-status", Static).update(f"{prefix}{message}[/]")

    def _update_panel_chrome(self) -> None:
        """统一步骤提示与主按钮文案。"""
        hints = {
            "mode": "Ctrl+Enter 进入所选类型 · Esc 返回指挥舱",
            "business-1": "Ctrl+Enter 开始调研 · Esc 上一步",
            "business-2": "Ctrl+Enter 确认扩建 · Esc 上一步",
            "role": "Ctrl+Enter 确认添加 · Esc 上一步",
            "manager": "Ctrl+Enter 确认创建 · Esc 上一步",
        }
        labels = {
            "mode": "继续",
            "business-1": "开始调研",
            "business-2": "确认扩建",
            "role": "确认添加",
            "manager": "确认创建",
        }
        variants = {
            "mode": "primary",
            "business-1": "primary",
            "business-2": "success",
            "role": "success",
            "manager": "success",
        }
        self.query_one("#page-hint", Static).update(f"[dim]{hints[self._panel]}[/]")
        btn = self.query_one("#btn-primary", Button)
        btn.label = labels[self._panel]
        btn.variant = variants[self._panel]
        btn.disabled = False

    def _show_panel(self, panel: str) -> None:
        self._panel = panel
        panels = {
            "mode": "panel-mode",
            "business-1": "panel-business-1",
            "business-2": "panel-business-2",
            "role": "panel-role",
            "manager": "panel-manager",
        }
        for key, pid in panels.items():
            self.query_one(f"#{pid}", Vertical).display = key == panel
        labels = {
            "mode": "选择扩建类型",
            "business-1": "新业务线 · 描述",
            "business-2": "新业务线 · 确认",
            "role": "部门内加人",
            "manager": "加管理层",
        }
        self.query_one("#expand-step-indicator", Static).update(f"步骤 · {labels.get(panel, '')}")
        self._update_panel_chrome()
        if panel == "business-1":
            self.query_one("#business-desc", Input).focus()

    def _position_options(self) -> list[tuple[str, str]]:
        return [
            (f"{p.get('name', p['id'])} · {p.get('title', '')} ({p['id']})", p["id"])
            for p in self._positions
        ]

    def _rebuild_role_selects(self) -> None:
        catalog = get_role_catalog()
        existing = {p["id"] for p in self._positions}
        role_opts = [
            (f"{meta.get('name')} · {meta.get('title')} ({rid})", rid)
            for rid, meta in catalog.items()
            if rid not in existing
        ]
        parent_opts = self._position_options()
        role_sel = self.query_one("#role-pick", Select)
        parent_sel = self.query_one("#role-parent", Select)
        if role_opts:
            role_sel.set_options(role_opts)
        else:
            role_sel.set_options([("（无可添加岗位）", "")])
        if parent_opts:
            parent_sel.set_options(parent_opts)

    def _rebuild_manager_panel(self) -> None:
        container = self.query_one("#manager-children-box", VerticalScroll)
        for cb in list(container.query(Checkbox)):
            cb.remove()
        workers = [p for p in self._positions if not p.get("is_manager")]
        for pos in workers:
            cb = Checkbox(
                f"{pos.get('name')} · {pos.get('title')} ({pos['id']})",
                value=False,
            )
            cb.child_id = pos["id"]  # type: ignore[attr-defined]
            container.mount(cb)

        reports = self.query_one("#manager-reports-to", Select)
        mgr_opts = [
            (f"{p.get('name')} ({p['id']})", p["id"])
            for p in self._positions
            if p.get("is_manager") or p.get("parent") is None
        ]
        if mgr_opts:
            reports.set_options(mgr_opts)

    def _enter_mode(self) -> None:
        mode = str(self.query_one("#expand-mode", Select).value or "")
        if mode == "business":
            self._mode = "business"
            self._show_panel("business-1")
        elif mode == "manager":
            self._mode = "manager"
            self._rebuild_manager_panel()
            self._show_panel("manager")
        elif mode == "role":
            self._mode = "role"
            self._rebuild_role_selects()
            self._show_panel("role")
        else:
            self._set_status("请选择扩建类型", error=True)

    def _run_business_research(self) -> None:
        desc = self.query_one("#business-desc", Input).value.strip() or "新业务"
        self._description = desc
        _, project_dir, _ = self._project_dir()
        result = mock_expand_research(desc, project_dir=project_dir)
        self._research_text = str(result["summary"])
        self._template_id = str(result["recommended_template"])
        data = load_positions_data(project_dir)
        missing = list_missing_roles(data, self._template_id)
        if not missing:
            missing = [
                r
                for r in (result.get("suggested_roles") or [])
                if r not in {p["id"] for p in self._positions}
            ]
        self._roles_to_add = missing
        self.query_one("#business-research", Static).update(self._research_text)
        if missing:
            preview = "将新增岗位: " + ", ".join(missing)
        else:
            preview = "[red]没有可新增岗位（组织已包含推荐编制）[/]"
        self.query_one("#business-roles-preview", Static).update(preview)
        self._show_panel("business-2")

    def _apply_business(self) -> None:
        if not self._roles_to_add:
            self._set_status("没有可新增岗位", error=True)
            return
        _, project_dir, _ = self._project_dir()
        try:
            expand_business_line(
                project_dir,
                self._description,
                template_id=self._template_id,
                role_ids=self._roles_to_add,
            )
        except (OrgTreeError, ValueError) as exc:
            self._set_status(str(exc), error=True)
            return
        self.dismiss(True)

    def _apply_role(self) -> None:
        role_sel = self.query_one("#role-pick", Select)
        parent_sel = self.query_one("#role-parent", Select)
        role_id = str(role_sel.value or "")
        parent_id = str(parent_sel.value or "")
        if not role_id or role_id == Select.BLANK:
            self._set_status("请选择要添加的岗位", error=True)
            return
        if not parent_id or parent_id == Select.BLANK:
            self._set_status("请选择上级", error=True)
            return
        _, project_dir, _ = self._project_dir()
        try:
            expand_add_role(project_dir, role_id, parent_id=parent_id)
        except (OrgTreeError, ValueError) as exc:
            self._set_status(str(exc), error=True)
            return
        self.dismiss(True)

    def _apply_manager(self) -> None:
        container = self.query_one("#manager-children-box", VerticalScroll)
        child_ids = [
            getattr(cb, "child_id", "")
            for cb in container.query(Checkbox)
            if cb.value and getattr(cb, "child_id", None)
        ]
        if not child_ids:
            self._set_status("请至少勾选一名下属", error=True)
            return
        new_id = self.query_one("#manager-id", Input).value.strip()
        new_name = self.query_one("#manager-name", Input).value.strip() or new_id
        reports = self.query_one("#manager-reports-to", Select)
        reports_to = str(reports.value or "")
        if not new_id:
            self._set_status("请填写新主管 id", error=True)
            return
        if not reports_to or reports_to == Select.BLANK:
            self._set_status("请选择新主管的上级", error=True)
            return
        spec = {
            "id": new_id,
            "name": new_name,
            "title": "组长",
            "parent": reports_to,
            "agent": "opencode",
            "model": "deepseek-v4-pro",
            "is_manager": True,
            "resume": {"strengths": ["团队协调", "任务分配"]},
        }
        _, project_dir, _ = self._project_dir()
        try:
            expand_insert_manager(project_dir, spec, child_ids)
        except OrgTreeError as exc:
            self._set_status(str(exc), error=True)
            return
        self.dismiss(True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-primary":
            self.action_primary_action()

    def action_primary_action(self) -> None:
        if self.query_one("#btn-primary", Button).disabled:
            return
        if self._panel == "mode":
            self._enter_mode()
        elif self._panel == "business-1":
            self._run_business_research()
        elif self._panel == "business-2":
            self._apply_business()
        elif self._panel == "role":
            self._apply_role()
        elif self._panel == "manager":
            self._apply_manager()

    def action_back(self) -> None:
        if self._panel == "mode":
            self.dismiss(False)
        elif self._panel == "business-1":
            self._show_panel("mode")
        elif self._panel == "business-2":
            self._show_panel("business-1")
        elif self._panel in ("role", "manager"):
            self._show_panel("mode")
