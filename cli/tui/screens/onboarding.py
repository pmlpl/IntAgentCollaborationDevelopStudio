# cli/tui/screens/onboarding.py — Phase 1.5 多步开公司向导
from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Checkbox, Footer, Header, Input, LoadingIndicator, Select, Static

from cli.tui.screens.position_editor import PositionEditorModal
from cli.tui.widgets.org_tree import render_org_tree
from core.project import (
    ORG_TEMPLATES,
    build_positions_data,
    customize_positions_data,
    default_project_path,
    get_studio_root,
    init_project,
    list_all_role_ids,
    list_org_templates,
    set_current_project,
    slug_project_name,
    validate_new_project,
    get_role_catalog,
)
from core.project_profile import create_stub_profile, update_profile_from_dict
from core.research.research import research_project
from core.supervisor_client import SupervisorClient


class OnboardingScreen(Screen):
    """多步向导：描述 → mock 调研 → 组织调整 → 路径确认。"""

    BINDINGS = [
        ("escape", "back", "返回"),
        ("ctrl+enter", "confirm", "确认"),
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

    def compose(self) -> ComposeResult:
        org_options = [(label, tid) for tid, label in list_org_templates()]
        yield Header(show_clock=True)
        yield Vertical(
            Static("[bold]新建项目[/]", classes="title-text"),
            Static("", id="step-indicator", classes="muted"),
            # Step 0: 项目描述
            Vertical(
                Static("第 1 步：你要做什么项目？", classes="muted"),
                Input(placeholder="例如：Vue3+FastAPI 记账应用", id="desc-input"),
                Button("下一步：调研", variant="primary", id="btn-step0-next"),
                id="step-0",
            ),
            # Step 1: AI 调研
            Vertical(
                LoadingIndicator(id="research-spinner"),
                Static("调研 Agent 正在联网检索并分析…", id="research-status-line", classes="accent"),
                Horizontal(
                    Button("上一步", id="btn-step1-back"),
                    Button("下一步：配置组织", variant="primary", id="btn-step1-next", disabled=True),
                ),
                VerticalScroll(
                    Static("", id="research-result", classes="panel-box"),
                    id="research-scroll",
                ),
                Static(
                    "[dim]调研完成后点击「下一步：配置组织」，或 Ctrl+Enter 继续[/]",
                    id="research-next-hint",
                    classes="muted",
                ),
                Vertical(
                    Static("可选：补充技术倾向后重新调研（逗号分隔）", classes="muted"),
                    Input(
                        placeholder="例如：Python Pygame / Vue3 / 微信小程序",
                        id="tech-stack-input",
                    ),
                    Horizontal(
                        Button("补充并重新调研", variant="primary", id="btn-apply-tech"),
                        Button("跳过，手动选组织", id="btn-skip-tech"),
                    ),
                    id="tech-stack-panel",
                ),
                id="step-1",
            ),
            # Step 2: 组织模板 + 岗位勾选 + 逐岗配置
            Vertical(
                Static("第 3 步：组织架构", classes="muted"),
                Select(org_options, value="web-fullstack", id="org-template"),
                Static("[2] 调整岗位（勾选启用）", classes="muted"),
                VerticalScroll(id="role-checkboxes"),
                Horizontal(
                    Button("逐岗配置 Agent/模型/花名", id="btn-edit-positions"),
                    Button("上一步", id="btn-step2-back"),
                    Button("下一步：选路径", variant="primary", id="btn-step2-next"),
                ),
                VerticalScroll(
                    Static("", id="org-preview", classes="panel-box"),
                    id="preview-scroll",
                ),
                id="step-2",
            ),
            # Step 3: 路径 + 确认
            Vertical(
                Static("第 4 步：项目文件夹", classes="muted"),
                Input(placeholder="例如：D:\\work\\ledger-app", id="path-input"),
                Horizontal(
                    Button("确认开工", variant="success", id="btn-confirm"),
                    Button("上一步", id="btn-step3-back"),
                ),
                Static("", id="confirm-error"),
                Static("路径框 Enter 确认 · Ctrl+Enter 确认开工", classes="muted"),
                id="step-3",
            ),
            id="onboard-container",
        )
        yield Footer()

    def on_mount(self) -> None:
        self._reset_wizard()
        self._show_step(0)
        self.query_one("#desc-input", Input).focus()

    def _reset_wizard(self) -> None:
        """每次进入向导时恢复初始状态（配合 push 新实例使用）。"""
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

        self.query_one("#desc-input", Input).value = ""
        self.query_one("#path-input", Input).value = ""
        self.query_one("#tech-stack-input", Input).value = ""
        self.query_one("#research-result", Static).update("")
        self.query_one("#research-status-line", Static).update("")
        self.query_one("#tech-stack-panel").display = True
        self.query_one("#research-spinner", LoadingIndicator).display = True
        self.query_one("#btn-step1-next", Button).disabled = True
        self.query_one("#org-preview", Static).update("")
        self._set_confirm_error("")

        tpl = self.query_one("#org-template", Select)
        self._suppress_org_select = True
        tpl.value = "web-fullstack"
        self._suppress_org_select = False

        container = self.query_one("#role-checkboxes", VerticalScroll)
        for cb in list(container.query(Checkbox)):
            cb.remove()

    def _show_step(self, step: int) -> None:
        self._step = step
        labels = ["1/4 项目描述", "2/4 调研", "3/4 组织架构", "4/4 路径确认"]
        self.query_one("#step-indicator", Static).update(f"步骤 {labels[step]}")
        for i in range(4):
            container = self.query_one(f"#step-{i}", Vertical)
            container.display = i == step
        if step == 1:
            if self._research_text:
                self._show_cached_research()
            else:
                self._run_research()
        if step == 2:
            tpl = self.query_one("#org-template", Select)
            self._suppress_org_select = True
            if self._template_id and str(tpl.value or "") != self._template_id:
                tpl.value = self._template_id
            self._suppress_org_select = False
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
        """调研 Agent：联网搜索 + AI 分析（后台线程，避免卡住 TUI）。"""
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
        self.query_one("#research-next-hint", Static).display = False
        self.query_one("#research-spinner", LoadingIndicator).display = True
        self.query_one("#btn-step1-next", Button).disabled = True
        self.query_one("#btn-apply-tech", Button).disabled = True

        self.run_worker(
            lambda: self._research_worker(desc, root, self._tech_stack),
            thread=True,
            exclusive=True,
            name="research-agent",
        )

    def _research_worker(self, desc: str, root: Path, tech_stack: str) -> dict:
        """后台执行调研 Agent。"""
        return research_project(desc, root, tech_stack=tech_stack)

    def on_worker_state_changed(self, event) -> None:
        if event.worker.name != "research-agent":
            return
        if event.worker.state.name == "SUCCESS":
            self._apply_research_result(event.worker.result)
        elif event.worker.state.name == "ERROR":
            self.query_one("#research-spinner", LoadingIndicator).display = False
            self.query_one("#research-status-line", Static).update("[red]调研失败[/]")
            self.query_one("#btn-apply-tech", Button).disabled = False
            self.query_one("#btn-step1-next", Button).disabled = False
            self.notify(str(event.worker.error), title="调研失败", severity="error")

    def _apply_research_result(self, result: dict) -> None:
        self._research_result = result
        self._research_text = str(result["summary"])
        self._template_id = str(result["recommended_template"])
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
        self.query_one("#research-next-hint", Static).display = True
        self.query_one("#tech-stack-panel").display = True
        self.query_one("#btn-apply-tech", Button).disabled = False
        self.query_one("#btn-step1-next", Button).disabled = False

    def _apply_tech_stack(self) -> None:
        self._run_research(use_tech_input=True)

    def _skip_tech_stack(self) -> None:
        """允许跳过，进入手动选组织。"""
        self._needs_tech_stack = False
        self.query_one("#btn-step1-next", Button).disabled = False
        self.query_one("#research-status-line", Static).update(
            "[dim]已跳过，下一步可手动选择组织模板[/]"
        )

    def _show_cached_research(self) -> None:
        """返回调研步时直接展示已有结果，不重复 loading。"""
        self.query_one("#research-spinner", LoadingIndicator).display = False
        self.query_one("#research-result", Static).update(self._research_text)
        self.query_one("#tech-stack-panel").display = True
        self.query_one("#btn-step1-next", Button).disabled = False
        if self._tech_stack:
            self.query_one("#tech-stack-input", Input).value = self._tech_stack

    def _org_template_id(self) -> str:
        if self._step < 2:
            return self._template_id
        value = self.query_one("#org-template", Select).value
        if value is Select.BLANK or not value:
            return self._template_id
        return str(value)

    def _rebuild_role_checkboxes(self) -> None:
        """根据模板生成岗位勾选列表（主管不可取消）。"""
        if self._role_checkbox_scheduled:
            return
        self._role_checkbox_scheduled = True
        container = self.query_one("#role-checkboxes", VerticalScroll)
        for cb in list(container.query(Checkbox)):
            cb.remove()

        template_id = self._org_template_id()
        template_roles = set(ORG_TEMPLATES[template_id]["roles"])
        catalog = get_role_catalog()
        items: list[tuple[str, str, bool, bool]] = []
        for rid in list_all_role_ids():
            meta = catalog[rid]
            in_template = rid in template_roles
            label = f"{meta.get('name')} · {meta.get('title')} ({rid})"
            checked = in_template and rid not in self._disabled_roles
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
        # 额外启用：模板外但被勾选的岗位
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
        self.query_one("#org-preview", Static).update(
            f"[dim]模板: {tpl}[/]\n\n{preview}"
        )

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if getattr(event.checkbox, "role_id", None):
            self._refresh_org_preview()

    def on_select_changed(self, event: Select.Changed) -> None:
        if self._suppress_org_select:
            return
        if event.select.id == "org-template" and self._step == 2:
            self._rebuild_role_checkboxes()
            self._refresh_org_preview()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "path-input":
            self._set_confirm_error("")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "path-input":
            self._confirm()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-step0-next":
            new_desc = self.query_one("#desc-input", Input).value.strip() or "新项目"
            if new_desc != self._description:
                self._research_text = ""
                self._tech_stack = ""
            self._description = new_desc
            self._show_step(1)
        elif bid == "btn-step1-next":
            self._show_step(2)
        elif bid == "btn-apply-tech":
            self._apply_tech_stack()
        elif bid == "btn-skip-tech":
            self._skip_tech_stack()
        elif bid == "btn-step1-back":
            self._show_step(0)
            self.query_one("#desc-input", Input).focus()
        elif bid == "btn-edit-positions":
            self._open_position_editor()
        elif bid == "btn-step2-next":
            try:
                self._build_final_positions_data()
            except ValueError as exc:
                self.query_one("#org-preview", Static).update(f"[red]{exc}[/]")
                return
            self._show_step(3)
        elif bid == "btn-step2-back":
            self._show_step(1)
        elif bid == "btn-step3-back":
            self._show_step(2)
        elif bid == "btn-confirm":
            self._confirm()

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
        else:
            self.app.pop_screen()

    def action_confirm(self) -> None:
        if self._step == 1 and not self.query_one("#btn-step1-next", Button).disabled:
            self._show_step(2)
            return
        if self._step == 3:
            self._confirm()

    def _set_confirm_error(self, message: str = "") -> None:
        """在第 4 步展示确认失败原因。"""
        widget = self.query_one("#confirm-error", Static)
        if message:
            widget.update(f"[red]{message}[/]")
        else:
            widget.update("")

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
