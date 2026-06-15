"""可折叠的模型配置栏 — 聊天 footer 区域的 model/key/baseurl 配置。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, Label, Static

from agents.chat_agent import AgentConfig, check_connection
from core.project import get_studio_root

# 配置文件名
_SETTINGS_FILE = "chat_settings.yaml"


def load_chat_settings(root: Path) -> dict[str, str]:
    """从 config/chat_settings.yaml 加载聊天模型配置。

    Returns:
        {"model": str, "api_key": str, "base_url": str}
    """
    path = root / "config" / _SETTINGS_FILE
    defaults = {"model": "claude", "api_key": "", "base_url": ""}
    if not path.is_file():
        return defaults
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        section = data.get("chat_model", {})
        if not isinstance(section, dict):
            return defaults
        return {
            "model": str(section.get("model") or defaults["model"]),
            "api_key": str(section.get("api_key") or defaults["api_key"]),
            "base_url": str(section.get("base_url") or defaults["base_url"]),
        }
    except Exception:
        return defaults


def save_chat_settings(root: Path, *, model: str, api_key: str, base_url: str) -> None:
    """保存聊天模型配置到 config/chat_settings.yaml。"""
    config_dir = root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / _SETTINGS_FILE

    # 读取已有文件保留其他 section
    existing: dict[str, Any] = {}
    if path.is_file():
        try:
            existing = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            existing = {}

    existing["chat_model"] = {
        "model": model,
        "api_key": api_key,
        "base_url": base_url,
    }
    path.write_text(
        yaml.dump(existing, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def mask_key(key: str) -> str:
    """掩码显示 API Key，仅显示末 4 字符。"""
    if not key:
        return "(未设置)"
    if len(key) <= 4:
        return key
    return "*" * (len(key) - 4) + key[-4:]


class ModelConfigBar(Vertical):
    """可折叠的模型配置栏。

    折叠态：一行摘要（模型名 │ key掩码 │ baseurl）
    展开态：三个 Input（模型名 / API Key / Base URL）+ 保存/折叠按钮
    """

    DEFAULT_CSS = """
    ModelConfigBar {
        height: auto;
        max-height: 12;
        background: #161b22;
        border-top: solid #30363d;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._expanded: bool = False
        self._model: str = "claude"
        self._api_key: str = ""
        self._base_url: str = ""
        self._connection_status: str = ""  # "ok" / "fail" / "" (未测试)

    @staticmethod
    def _root() -> Path:
        """获取 studio 根目录（始终可用，不依赖外部传入）。"""
        return get_studio_root()

    def compose(self) -> ComposeResult:
        # 折叠态摘要
        yield Static(self._build_summary(), id="config-summary")
        # 展开态输入区（初始隐藏）
        yield Vertical(
            Horizontal(
                Label("模型:", classes="config-label"),
                Input(value=self._model, id="config-model", classes="config-input"),
                classes="config-row",
            ),
            Horizontal(
                Label("Key:", classes="config-label"),
                Input(
                    value=self._api_key,
                    password=True,
                    id="config-key",
                    classes="config-input",
                ),
                classes="config-row",
            ),
            Horizontal(
                Label("URL:", classes="config-label"),
                Input(
                    value=self._base_url,
                    placeholder="(空=使用默认)",
                    id="config-url",
                    classes="config-input",
                ),
                classes="config-row",
            ),
            Horizontal(
                Button("测试", variant="default", id="config-test"),
                Button("保存", variant="primary", id="config-save"),
                Button("折叠", variant="default", id="config-collapse"),
                classes="config-actions",
            ),
            id="config-expanded",
        )
        # 连接测试状态行（初始隐藏）
        yield Static("", id="config-test-status")

    def on_mount(self) -> None:
        """加载保存的配置。"""
        settings = load_chat_settings(self._root())
        self._model = settings["model"]
        self._api_key = settings["api_key"]
        self._base_url = settings["base_url"]
        # 更新输入框初始值
        self._sync_inputs()
        self._update_summary()
        # 默认折叠，隐藏测试状态
        self.query_one("#config-expanded").display = False
        self.query_one("#config-test-status").display = False

    def _sync_inputs(self) -> None:
        """将内部状态同步到输入框。"""
        self.query_one("#config-model", Input).value = self._model
        self.query_one("#config-key", Input).value = self._api_key
        self.query_one("#config-url", Input).value = self._base_url

    def _build_summary(self) -> str:
        """构建折叠态摘要文本。"""
        key_display = mask_key(self._api_key)
        url_display = self._base_url or "默认"
        if self._connection_status == "ok":
            status = " [#3fb950]✓ 已连接[/]"
        elif self._connection_status == "fail":
            status = " [red]✗ 连接失败[/]"
        else:
            status = ""
        return f"  [dim]▸[/] [#58a6ff]{self._model}[/] [dim]│[/] {key_display} [dim]│[/] {url_display}{status}"

    def _update_summary(self) -> None:
        """刷新折叠态摘要。"""
        self.query_one("#config-summary", Static).update(self._build_summary())

    def toggle(self) -> None:
        """切换展开/折叠。"""
        self._expanded = not self._expanded
        expanded = self.query_one("#config-expanded")
        summary = self.query_one("#config-summary")
        status = self.query_one("#config-test-status")
        if self._expanded:
            # 展开时同步当前值到输入框
            self._sync_inputs()
            expanded.display = True
            summary.display = False
            status.display = False
            # 聚焦到模型输入框
            self.set_timer(0.05, lambda: self.query_one("#config-model", Input).focus())
        else:
            expanded.display = False
            summary.display = True
            status.display = False

    def _save(self) -> None:
        """保存配置到文件。"""
        self._model = self.query_one("#config-model", Input).value.strip()
        self._api_key = self.query_one("#config-key", Input).value
        self._base_url = self.query_one("#config-url", Input).value.strip()

        save_chat_settings(
            self._root(),
            model=self._model,
            api_key=self._api_key,
            base_url=self._base_url,
        )

        self._update_summary()
        self.toggle()

    def build_agent_config(self) -> AgentConfig:
        """从当前配置构建 AgentConfig 实例。"""
        return AgentConfig(
            model=self._model,
            api_key=self._api_key,
            base_url=self._base_url,
        )

    def get_current_model(self) -> str:
        """获取当前模型名（折叠态读取用）。"""
        return self._model

    # ── 事件处理 ──

    def _run_test_connection(self) -> None:
        """测试连接（读取输入框当前值，不保存）。"""
        model = self.query_one("#config-model", Input).value.strip()
        api_key = self.query_one("#config-key", Input).value
        base_url = self.query_one("#config-url", Input).value.strip()

        # 显示测试中状态
        status = self.query_one("#config-test-status")
        status.update("[#d29922]⏳ 正在测试连接…[/]")
        status.display = True

        config = AgentConfig(model=model, api_key=api_key, base_url=base_url)
        self._do_test_connection(config)

    @work(thread=True, exclusive=True)
    def _do_test_connection(self, config: AgentConfig) -> None:
        """后台线程执行连接测试。"""
        ok, msg = check_connection(config)
        self.app.call_from_thread(self._on_test_result, ok, msg)

    def _on_test_result(self, ok: bool, msg: str) -> None:
        """处理测试结果（主线程）。"""
        status = self.query_one("#config-test-status")
        if ok:
            status.update(f"[#3fb950]✅ 连接成功[/] [dim]{msg}[/]")
            self._connection_status = "ok"
        else:
            status.update(f"[red]❌ 连接失败[/] [dim]{msg}[/]")
            self._connection_status = "fail"
        self._update_summary()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "config-save":
            self._save()
        elif event.button.id == "config-collapse":
            self.toggle()
        elif event.button.id == "config-test":
            self._run_test_connection()
