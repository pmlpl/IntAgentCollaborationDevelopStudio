# cli/tui/screens/onboarding.py — 多步开公司向导（统一全屏布局）
from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Checkbox, Footer, Header, Input, LoadingIndicator, Select, Static

from cli.tui.screens.position_editor import PositionEditorModal
from cli.tui.widgets.org_tree import render_org_tree
from core.config.select_helpers import safe_select_value, ui_select_options
from core.project import (
    ORG_TEMPLATES,
    build_positions_data,
    customize_positions_data,
    default_project_path,
    get_role_catalog,
    get_studio_root,
    init_project,
    list_all_role_ids,
    list_org_templates,
    set_current_project,
    slug_project_name,
    validate_new_project,
)
from core.project_profile import create_stub_profile, update_profile_from_dict
from core.research.research import research_project
from core.supervisor_client import SupervisorClient


class OnboardingScreen(Screen):
    """多步向导：描述 → 调研 → 组织 → 路径。"""

    BINDINGS = [
        ("escape", "back", "返回"),
        ("ctrl+enter", "primary_action", "继续"),
        ("e", "edit_positions", "逐岗配置"),
        ("r", "research_tech", "重新调研"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._step = 0
        self._description = ""
        self._template_id = "web-fullstack"
        self._research_text = ""
        self._disabled_roles: set[str] = set()
        self._position_overrides: dict[str, dict] = {}
        self._base_positions_data: dict | None = None
        self._suppress_org_select = False
        self._role_checkbox_scheduled = False
        self._tech_stack = ""
        self._needs_tech_stack = False
        self._matched_keywords: list[str] = []
        self._research_result: dict | None = None
        self._recommended_roles: set[str] = set()

    def compose(self) -> ComposeResult:
        org_options = ui_select_options(list_org_templates())
        yield Header(show_clock=True)
        yield Container(
            VerticalScroll(
                Static("[bold]新建项目[/]", classes="title-text"),
                Static("", id="step-indicator", classes="muted"),
                Vertical(
                    Static("你要做什么项目？", classes="accent"),
                    Input(placeholder="例如：Vue3+FastAPI 记账应用", id="desc-input"),
                    id="step-0",
                    classes="page-step",
                ),
                Vertical(
                    LoadingIndicator(id="research-spinner"),
                    Static("调研 Agent 正在联网检索并分析…", id="research-status-line", classes="accent"),
                    VerticalScroll(
                        Static("", id="research-result", classes="panel-box"),
                        id="research-scroll",
                        classes="page-scroll",
                    ),
                    Static("可选：补充技术倾向后按 R 重新调研", classes="muted"),
                    Input(
                        placeholder="例如：Python Pygame / Vue3 / 微信小程序",
                        id="tech-stack-input",
                    ),
                    id="step-1",
                    classes="page-step",
                ),
                Vertical(
                    Static("组织架构", classes="accent"),
                    Static("", id="research-roles-hint", classes="muted"),
                    Static("调研推荐岗位（可勾选调整）", classes="muted"),
                    VerticalScroll(id="role-checkboxes", classes="page-scroll"),
                    Static("套用模板（可选，会重置岗位勾选）", classes="muted"),
                    Select(org_options, value="web-fullstack", id="org-template"),
                    VerticalScroll(
                        Static("", id="org-preview", classes="panel-box"),
                        id="preview-scroll",
                        classes="page-scroll",
                    ),
                    id="step-2",
                    classes="page-step",
                ),
                Vertical(
                    Static("项目文件夹", classes="accent"),
                    Input(placeholder="例如：D:\\work\\ledger-app", id="path-input"),
                    Static("", id="confirm-error"),
                    id="step-3",
                    classes="page-step",
                ),
                classes="page-body",
            ),
            Static("", id="page-hint", classes="page-hint"),
            Horizontal(
                Button("继续", variant="primary", id="btn-primary"),
                classes="page-actions",
            ),
            id="onboard-container",
            classes="page-shell",
        )
        yield Footer()

    def on_mount(self) -> None:
        self._reset_wizard()
        self._show_step(0)
        self.query_one("#desc-input", Input).focus()

    def _reset_wizard(self) -> None:
        """每次进入向导时恢复初始状态。"""
        self._step = 0
        self._description = ""
        self._template_id = "web-fullstack"
        self._research_text = ""
        self._disabled_roles = set()
        self._position_overrides = {}
        self._base_positions_data = None
        self._suppress_org_select = False
        self._role_checkbox_scheduled = False
        self._tech_stack = ""
        self._needs_tech_stack = False
        self._matched_keywords: list[str] = []
        self._research_result: dict | None = None
        self._recommended_roles = set()

        self.query_one("#desc-input", Input).value = ""
        self.query_one("#path-input", Input).value = ""
        self.query_one("#tech-stack-input", Input).value = ""
        self.query_one("#research-result", Static).update("")
        self.query_one("#research-status-line", Static).update("")
        self.query_one("#research-spinner", LoadingIndicator).display = True
        self._set_primary_enabled(False)
        self.query_one("#org-preview", Static).update("")
        self._set_confirm_error("")

        tpl = self.query_one("#org-template", Select)
        self._suppress_org_select = True
        safe_select_value(tpl, self._template_id or "web-fullstack", fallback="web-fullstack")
        self._suppress_org_select = False

        container = self.query_one("#role-checkboxes", VerticalScroll)
        for cb in list(container.query(Checkbox)):
            cb.remove()

    def _set_primary_enabled(self, enabled: bool) -> None:
        self.query_one("#btn-primary", Button).disabled = not enabled

    def _update_step_chrome(self) -> None:
        """统一步骤提示与主按钮文案。"""
        hints = {
            0: "Ctrl+Enter 开始调研 · Esc 返回",
            1: "Ctrl+Enter 继续 · R 补充技术后重新调研 · Esc 上一步",
            2: "Ctrl+Enter 继续 · E 逐岗配置 · Esc 上一步",
            3: "Ctrl+Enter 确认开工 · Esc 上一步",
        }
        labels = {
            0: "开始调研",
            1: "继续",
            2: "继续",
            3: "确认开工",
        }
        self.query_one("#page-hint", Static).update(f"[dim]{hints[self._step]}[/]")
        btn = self.query_one("#btn-primary", Button)
        btn.label = labels[self._step]
        btn.variant = "success" if self._step == 3 else "primary"
        if self._step == 0:
            self._set_primary_enabled(True)
        elif self._step == 1:
            self._set_primary_enabled(bool(self._research_text))
        elif self._step in (2, 3):
            self._set_primary_enabled(True)

    def _show_step(self, step: int) -> None:
        self._step = step
        labels = ["1/4 项目描述", "2/4 调研", "3/4 组织架构", "4/4 路径确认"]
        self.query_one("#step-indicator", Static).update(f"步骤 · {labels[step]}")
        for i in range(4):
            self.query_one(f"#step-{i}", Vertical).display = i == step
        self._update_step_chrome()
        if step == 1:
            if self._research_text:
                self._show_cached_research()
            else:
                self._run_research()
        if step == 2:
            tpl = self.query_one("#org-template", Select)
            self._suppress_org_select = True
            safe_select_value(tpl, self._template_id or "web-fullstack", fallback="web-fullstack")
            self._suppress_org_select = False
            self._update_research_roles_hint()
            container = self.query_one("#role-checkboxes", VerticalScroll)
            if not list(container.query(Checkbox)):
                self._rebuild_role_checkboxes()
            else:
                self._refresh_org_preview()
        if step == 3:
            self._sync_path_default(self._description)
            self._set_confirm_error("")
            self.query_one("#path-input", Input).focus()

    def _run_research(self, *, use_tech_input: bool = False) -> None:
        """调研 Agent：联网搜索 + AI 分析（后台线程）。"""
        desc = self.query_one("#desc-input", Input).value.strip() or "新项目"
        self._description = desc
        tech = self.query_one("#tech-stack-input", Input).value.strip()
        if use_tech_input or tech:
            self._tech_stack = tech

        root = get_studio_root()
        self.query_one("#research-result", Static).update("[dim]正在联网调研，请稍候…[/]")
        self.query_one("#research-status-line", Static).update(
            "[yellow]▶ 第 1 步：联网检索 → 第 2 步：Claude 调研分析…[/]"
        )
        self.query_one("#research-spinner", LoadingIndicator).display = True
        self._set_primary_enabled(False)

        self.run_worker(
            lambda: self._research_worker(desc, root, self._tech_stack),
            thread=True,
            exclusive=True,
            name="research-agent",
        )

    def _research_worker(self, desc: str, root: Path, tech_stack: str) -> dict:
        return research_project(desc, root, tech_stack=tech_stack)

    def on_worker_state_changed(self, event) -> None:
        if event.worker.name != "research-agent":
            return
        if event.worker.state.name == "SUCCESS":
            self._apply_research_result(event.worker.result)
        elif event.worker.state.name == "ERROR":
            self.query_one("#research-spinner", LoadingIndicator).display = False
            self.query_one("#research-status-line", Static).update("[red]调研失败[/]")
            self._set_primary_enabled(True)
            self.notify(str(event.worker.error), title="调研失败", severity="error")

    def _apply_research_result(self, result: dict) -> None:
        self._research_result = result
        self._research_text = str(result["summary"])
        self._template_id = str(result["recommended_template"])
        roles = list(result.get("recommended_roles") or [])
        self._recommended_roles = set(roles) if roles else set(
            ORG_TEMPLATES.get(self._template_id, ORG_TEMPLATES["web-fullstack"])["roles"]
        )
        self._disabled_roles = set()
        self._matched_keywords = list(result.get("technologies") or [])
        self._needs_tech_stack = bool(result.get("needs_tech_stack"))

        src = str(result.get("source", ""))
        web_label = str(result.get("web_search_label") or f"联网 {int(result.get('web_hit_count') or 0)} 条")
        search_ms = int(result.get("web_search_elapsed_ms") or 0)
        agent_ok = result.get("agent_available", True)
        timing = f" · 检索耗时 {search_ms // 1000}s" if search_ms >= 1000 else ""
        if src == "agent":
            status = f"[green]✓ 调研 Agent 已完成[/] · {web_label}{timing}"
        elif src == "local":
            status = f"[green]✓ 本地模型调研已完成[/] · {web_label}{timing}"
        elif src == "offline":
            status = f"[yellow]⚠ 离线分析[/] · {web_label}{timing}"
            if not agent_ok:
                status += " · Agent 不可用"
        else:
            status = f"[dim]调研完成 ({src})[/] · {web_label}"

        self.query_one("#research-status-line", Static).update(status)
        self.query_one("#research-spinner", LoadingIndicator).display = False
        self.query_one("#research-result", Static).update(self._research_text)
        self._set_primary_enabled(True)

    def _apply_tech_stack(self) -> None:
        self._run_research(use_tech_input=True)

    def _show_cached_research(self) -> None:
        """返回调研步时直接展示已有结果。"""
        self.query_one("#research-spinner", LoadingIndicator).display = False
        self.query_one("#research-result", Static).update(self._research_text)
        self._set_primary_enabled(True)
        if self._tech_stack:
            self.query_one("#tech-stack-input", Input).value = self._tech_stack

    def _org_template_id(self) -> str:
        if self._step < 2:
            return self._template_id
        value = self.query_one("#org-template", Select).value
        if value is Select.BLANK or not value:
            return self._template_id
        return str(value)

    def _update_research_roles_hint(self) -> None:
        catalog = get_role_catalog()
        if not self._recommended_roles:
            self.query_one("#research-roles-hint", Static).update(
                "[dim]根据调研结果勾选岗位；也可套用下方模板[/]"
            )
            return
        names = [
            f"{catalog[r]['name']}({r})"
            for r in self._recommended_roles
            if r in catalog
        ]
        self.query_one("#research-roles-hint", Static).update(
            f"[green]调研推荐[/]：{' · '.join(names)}"
        )

    def _roles_for_checkboxes(self) -> set[str]:
        if self._recommended_roles:
            return set(self._recommended_roles)
        template_id = self._org_template_id()
        return set(ORG_TEMPLATES.get(template_id, ORG_TEMPLATES["web-fullstack"])["roles"])

    def _rebuild_role_checkboxes(self) -> None:
        if self._role_checkbox_scheduled:
            return
        self._role_checkbox_scheduled = True
        container = self.query_one("#role-checkboxes", VerticalScroll)
        for cb in list(container.query(Checkbox)):
            cb.remove()

        template_id = self._org_template_id()
        template_roles = set(ORG_TEMPLATES[template_id]["roles"])
        enabled = self._roles_for_checkboxes()
        catalog = get_role_catalog()
        items: list[tuple[str, str, bool, bool]] = []
        for rid in list_all_role_ids():
            meta = catalog[rid]
            label = f"{meta.get('name')} · {meta.get('title')} ({rid})"
            checked = rid in enabled and rid not in self._disabled_roles
            if rid == "laowang":
                checked = True
            items.append((rid, label, checked, rid == "laowang"))

        def _mount_checkboxes() -> None:
            self._role_checkbox_scheduled = False
            for rid, label, checked, locked in items:
                cb = Checkbox(label, value=checked)
                cb.role_id = rid  # type: ignore[attr-defined]
                cb.disabled = locked
                container.mount(cb)
            self._refresh_org_preview()

        self.call_after_refresh(_mount_checkboxes)

    def _build_final_positions_data(self) -> dict:
        name = slug_project_name(self._description)
        template_id = self._org_template_id()
        base = build_positions_data(name, self._description, template_id)
        catalog = get_role_catalog()
        container = self.query_one("#role-checkboxes", VerticalScroll)
        enabled_extra: list[str] = []
        template_roles = set(ORG_TEMPLATES[template_id]["roles"])
        disabled: set[str] = set()
        for cb in container.query(Checkbox):
            rid = getattr(cb, "role_id", "")
            if not rid:
                continue
            if cb.value:
                if rid not in template_roles and rid in catalog:
                    enabled_extra.append(rid)
            elif rid != "laowang":
                disabled.add(rid)
        if enabled_extra:
            base = build_positions_data(
                name, self._description, template_id, extra_role_ids=enabled_extra
            )
        return customize_positions_data(
            base,
            disabled_role_ids=disabled,
            overrides=self._position_overrides,
        )

    def _refresh_org_preview(self) -> None:
        try:
            data = self._build_final_positions_data()
        except ValueError as exc:
            self.query_one("#org-preview", Static).update(f"[red]{exc}[/]")
            return
        self._base_positions_data = data
        preview = render_org_tree(data["positions"])
        tpl = ORG_TEMPLATES[self._org_template_id()]["label"]
        self.query_one("#org-preview", Static).update(f"[dim]模板: {tpl}[/]\n\n{preview}")

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        rid = getattr(event.checkbox, "role_id", None)
        if not rid:
            return
        if event.checkbox.value:
            self._disabled_roles.discard(rid)
            self._recommended_roles.add(rid)
        elif rid != "laowang":
            self._disabled_roles.add(rid)
            self._recommended_roles.discard(rid)
        self._refresh_org_preview()

    def on_select_changed(self, event: Select.Changed) -> None:
        if self._suppress_org_select:
            return
        if event.select.id == "org-template" and self._step == 2:
            tid = str(event.value or self._template_id)
            if tid in ORG_TEMPLATES:
                self._template_id = tid
                self._recommended_roles = set(ORG_TEMPLATES[tid]["roles"])
                self._disabled_roles = set()
                self._update_research_roles_hint()
            self._rebuild_role_checkboxes()
            self._refresh_org_preview()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "path-input":
            self._set_confirm_error("")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "path-input" and self._step == 3:
            self.action_primary_action()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-primary":
            self.action_primary_action()

    def action_primary_action(self) -> None:
        if self.query_one("#btn-primary", Button).disabled:
            return
        if self._step == 0:
            new_desc = self.query_one("#desc-input", Input).value.strip() or "新项目"
            if new_desc != self._description:
                self._research_text = ""
                self._tech_stack = ""
            self._description = new_desc
            self._show_step(1)
        elif self._step == 1:
            self._show_step(2)
        elif self._step == 2:
            try:
                self._build_final_positions_data()
            except ValueError as exc:
                self.query_one("#org-preview", Static).update(f"[red]{exc}[/]")
                return
            self._show_step(3)
        elif self._step == 3:
            self._confirm()

    def action_edit_positions(self) -> None:
        if self._step != 2:
            return
        self._open_position_editor()

    def action_research_tech(self) -> None:
        if self._step != 1:
            return
        self._apply_tech_stack()

    def _open_position_editor(self) -> None:
        try:
            data = self._build_final_positions_data()
        except ValueError as exc:
            self.query_one("#org-preview", Static).update(f"[red]{exc}[/]")
            return

        def on_done(overrides: dict[str, dict] | None) -> None:
            if overrides is not None:
                self._position_overrides = overrides
                self._refresh_org_preview()

        self.app.push_screen(PositionEditorModal(data["positions"]), on_done)

    def action_back(self) -> None:
        if self._step > 0:
            self._show_step(self._step - 1)
            if self._step == 0:
                self.query_one("#desc-input", Input).focus()
        else:
            self.app.pop_screen()

    def _set_confirm_error(self, message: str = "") -> None:
        widget = self.query_one("#confirm-error", Static)
        widget.update(f"[red]{message}[/]" if message else "")

    def _sync_path_default(self, description: str) -> None:
        path_input = self.query_one("#path-input", Input)
        if path_input.value.strip():
            return
        root = get_studio_root()
        slug = slug_project_name(description)
        path_input.value = str(default_project_path(root, slug))

    def _confirm(self) -> None:
        desc = self._description or self.query_one("#desc-input", Input).value.strip() or "新项目"
        path_text = self.query_one("#path-input", Input).value.strip()
        if not path_text:
            self._set_confirm_error("请填写项目文件夹路径")
            return

        root = get_studio_root()
        name = slug_project_name(desc)
        project_path = Path(path_text)

        if err := validate_new_project(root, name, project_path):
            self._set_confirm_error(err)
            return

        self._set_confirm_error("")

        try:
            positions_data = self._build_final_positions_data()
        except ValueError:
            self._show_step(2)
            return

        SupervisorClient(root).ensure_running()
        try:
            data_dir = init_project(
                root,
                name,
                project_path=project_path,
                description=desc,
                positions_data=positions_data,
            )
        except (FileExistsError, OSError) as exc:
            self._set_confirm_error(str(exc))
            return

        if self._research_result:
            update_profile_from_dict(data_dir, self._research_result, desc)
        else:
            create_stub_profile(data_dir, desc)

        set_current_project(root, name)
        self.app.project_name = name
        self.app.auto_open_task_dispatch = True
        self.app.switch_screen("dashboard")
