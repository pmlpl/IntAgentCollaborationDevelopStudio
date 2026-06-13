# core/research/local_llm.py — 调研用本地大模型（LM Studio / Ollama）
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

import yaml

from core.project import get_studio_root


def _load_research_section(root: Path | None = None) -> dict[str, Any]:
    """读取 platform.yaml 中 research 整段配置。"""
    base = root or get_studio_root()
    path = base / "config" / "platform.yaml"
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get("research") or {}


def _load_lmstudio_config(root: Path | None = None) -> dict[str, Any]:
    """读取 research.lmstudio 段。"""
    return _load_research_section(root).get("lmstudio") or {}


def _load_ollama_config(root: Path | None = None) -> dict[str, Any]:
    """读取 research.ollama 段（保留兼容）。"""
    return _load_research_section(root).get("ollama") or {}


def _http_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout: int = 30,
    api_key: str | None = None,
) -> tuple[int, dict[str, Any] | str]:
    """发起 JSON HTTP 请求，成功返回 (0, dict)，失败返回 (1, 错误信息)。"""
    data = None
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return 0, json.loads(body) if body.strip() else {}
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        return 1, f"网络错误: {reason}"
    except TimeoutError:
        return 1, f"请求超时（>{timeout}s）"
    except json.JSONDecodeError as exc:
        return 1, f"响应非 JSON: {exc}"
    except Exception as exc:
        return 1, f"{type(exc).__name__}: {exc}"


def lmstudio_available(root: Path | None = None) -> bool:
    """LM Studio 本地 OpenAI 兼容服务是否可用。"""
    cfg = _load_lmstudio_config(root)
    base_url = str(cfg.get("base_url") or "http://127.0.0.1:1234/v1").rstrip("/")
    timeout = int(cfg.get("timeout_sec") or 5)
    rc, _ = _http_json(f"{base_url}/models", timeout=timeout)
    return rc == 0


def run_lmstudio_prompt_capture(
    prompt: str,
    root: Path | None = None,
) -> tuple[int, str]:
    """调用 LM Studio /v1/chat/completions。"""
    cfg = _load_lmstudio_config(root)
    base_url = str(cfg.get("base_url") or "http://127.0.0.1:1234/v1").rstrip("/")
    model = str(cfg.get("model") or "local-model")
    timeout = int(cfg.get("timeout_sec") or 120)
    temperature = float(cfg.get("temperature") or 0.3)

    rc, raw = _http_json(
        f"{base_url}/chat/completions",
        method="POST",
        payload={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "stream": False,
        },
        timeout=timeout,
        api_key=str(cfg.get("api_key") or "").strip() or None,
    )
    if rc != 0:
        return 1, f"LM Studio 连接失败: {raw}"

    if not isinstance(raw, dict):
        return 1, "LM Studio 响应格式异常"

    choices = raw.get("choices") or []
    if not choices:
        return 1, "LM Studio 返回空 choices"
    message = choices[0].get("message") or {}
    content = str(message.get("content") or "").strip()
    if not content:
        return 1, "LM Studio 返回空内容"
    return 0, content


def ollama_available(root: Path | None = None) -> bool:
    """Ollama 服务是否在本地可访问。"""
    cfg = _load_ollama_config(root)
    base_url = str(cfg.get("base_url") or "http://127.0.0.1:11434").rstrip("/")
    timeout = int(cfg.get("timeout_sec") or 5)
    req = urllib.request.Request(f"{base_url}/api/tags", method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def run_ollama_prompt_capture(
    prompt: str,
    root: Path | None = None,
) -> tuple[int, str]:
    """调用 Ollama /api/chat。"""
    cfg = _load_ollama_config(root)
    base_url = str(cfg.get("base_url") or "http://127.0.0.1:11434").rstrip("/")
    model = str(cfg.get("model") or "qwen2.5:7b")
    timeout = int(cfg.get("timeout_sec") or 120)

    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        },
        ensure_ascii=False,
    ).encode("utf-8")

    req = urllib.request.Request(
        f"{base_url}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        return 1, f"Ollama 连接失败: {reason}"
    except TimeoutError:
        return 1, f"Ollama 请求超时（>{timeout}s）"
    except Exception as exc:
        return 1, f"Ollama 错误: {type(exc).__name__}: {exc}"

    content = str((raw.get("message") or {}).get("content") or "").strip()
    if not content:
        return 1, "Ollama 返回空内容"
    return 0, content


_LOCAL_BACKENDS: dict[str, tuple[Callable[..., bool], Callable[..., tuple[int, str]]]] = {
    "lmstudio": (lmstudio_available, run_lmstudio_prompt_capture),
    "ollama": (ollama_available, run_ollama_prompt_capture),
}


def local_llm_available(mode: str, root: Path | None = None) -> bool:
    """按调研 mode 检测对应本地后端是否在线。"""
    pair = _LOCAL_BACKENDS.get(mode)
    if not pair:
        return False
    return pair[0](root)


def run_local_prompt_capture(
    prompt: str,
    mode: str,
    root: Path | None = None,
) -> tuple[int, str]:
    """按调研 mode 调用 LM Studio 或 Ollama。"""
    pair = _LOCAL_BACKENDS.get(mode)
    if not pair:
        return 1, f"未知本地后端: {mode}"
    return pair[1](prompt, root)
