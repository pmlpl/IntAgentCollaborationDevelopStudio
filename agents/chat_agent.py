"""内置聊天 Agent — 直接调用 Anthropic API，不依赖外部 CLI。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from core.logging import get_logger

logger = get_logger(__name__)

# 可用模型 → 实际 API model ID
_MODEL_MAP: dict[str, str] = {
    "claude": "claude-sonnet-4-6",
    "claude-sonnet": "claude-sonnet-4-6",
    "claude-opus": "claude-opus-4-6",
    "claude-haiku": "claude-haiku-4-5",
    "deepseek": "deepseek-chat",
    "gpt": "gpt-4o",
    "gemini": "gemini-2.0-flash",
}

# 默认 system prompt
DEFAULT_SYSTEM_PROMPT = (
    "你是项目中的主管（Manager），负责与 CEO 对话。\n"
    "你管理一个由多个 Worker Agent 组成的团队，负责任务分解、分配和审查。\n"
    "请用中文简洁回复。如果 CEO 提的是任务需求，给出你的分析和建议。\n"
    "如果需要更多信息，提出你的问题。"
)


@dataclass
class AgentConfig:
    """聊天 Agent 配置。"""
    model: str = "claude"
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    max_tokens: int = 4096
    temperature: float = 0.7
    api_key: str = ""
    base_url: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def _get_api_key(config: AgentConfig) -> str:
    """获取 API Key（优先使用配置，回退到环境变量）。"""
    if config.api_key:
        return config.api_key
    # 根据模型选择环境变量
    model_id = _MODEL_MAP.get(config.model, "")
    if model_id.startswith("claude"):
        return os.environ.get("ANTHROPIC_API_KEY", "")
    elif model_id.startswith("gpt"):
        return os.environ.get("OPENAI_API_KEY", "")
    elif model_id.startswith("deepseek"):
        return os.environ.get("DEEPSEEK_API_KEY", "")
    elif model_id.startswith("gemini"):
        return os.environ.get("GOOGLE_API_KEY", "")
    return ""


def check_connection(config: AgentConfig) -> tuple[bool, str]:
    """测试 API 连接是否正常。

    发送一条最短请求，验证 key / model / base_url 是否正确。

    Returns:
        (success, message) — success=True 时 message 包含实际模型标识；False 时为错误信息
    """
    model_id = _MODEL_MAP.get(config.model, config.model)
    api_key = _get_api_key(config)

    if not api_key:
        return False, f"未设置 API Key（需要 {_env_hint(config.model)}）"

    # Claude 模型：用 Anthropic SDK
    if model_id.startswith("claude"):
        try:
            import anthropic
            client_kwargs: dict[str, Any] = {"api_key": api_key}
            if config.base_url:
                client_kwargs["base_url"] = config.base_url
            client = anthropic.Anthropic(**client_kwargs)
            response = client.messages.create(
                model=model_id,
                max_tokens=10,
                messages=[{"role": "user", "content": "hi"}],
            )
            # 返回实际使用的模型 ID
            actual_model = getattr(response, "model", model_id)
            return True, f"已连接 {actual_model}"
        except Exception as exc:
            return False, str(exc)[:120]

    # 其他模型：用 OpenAI 兼容接口
    try:
        import openai
    except ImportError:
        return False, "需要安装 openai 包: pip install openai"

    base_url = config.base_url or None
    if not base_url:
        if model_id.startswith("deepseek"):
            base_url = "https://api.deepseek.com/v1"
        elif model_id.startswith("gemini"):
            base_url = "https://generativelanguage.googleapis.com/v1beta/openai"

    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url

    try:
        client = openai.OpenAI(**client_kwargs)
        response = client.chat.completions.create(
            model=model_id,
            max_tokens=10,
            messages=[{"role": "user", "content": "hi"}],
        )
        actual_model = getattr(response, "model", model_id)
        return True, f"已连接 {actual_model}"
    except Exception as exc:
        return False, str(exc)[:120]


def chat_agent_respond(
    config: AgentConfig,
    user_message: str,
    history: list[dict[str, str]] | None = None,
) -> str:
    """调用 Agent API 获取回复（同步，非流式）。

    Args:
        config: Agent 配置
        user_message: 用户消息
        history: 历史对话 [{"role": "user"/"assistant", "content": "..."}]

    Returns:
        Agent 的回复文本

    Raises:
        RuntimeError: API 调用失败
    """
    model_id = _MODEL_MAP.get(config.model, config.model)
    api_key = _get_api_key(config)

    if not api_key:
        raise RuntimeError(
            f"未找到 API Key。请设置环境变量或在 /model 中选择已配置密钥的模型。\n"
            f"模型 '{config.model}' 需要: {_env_hint(config.model)}"
        )

    # Claude 模型：用 Anthropic SDK
    if model_id.startswith("claude"):
        return _call_anthropic(api_key, model_id, config, user_message, history)

    # 其他模型：用 OpenAI 兼容接口
    return _call_openai_compatible(api_key, model_id, config, user_message, history)


def _env_hint(model_key: str) -> str:
    """返回模型需要的环境变量提示。"""
    hints = {
        "claude": "ANTHROPIC_API_KEY",
        "claude-sonnet": "ANTHROPIC_API_KEY",
        "claude-opus": "ANTHROPIC_API_KEY",
        "claude-haiku": "ANTHROPIC_API_KEY",
        "gpt": "OPENAI_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "gemini": "GOOGLE_API_KEY",
    }
    return hints.get(model_key, "对应 API Key")


def _call_anthropic(
    api_key: str,
    model_id: str,
    config: AgentConfig,
    user_message: str,
    history: list[dict[str, str]] | None,
) -> str:
    """调用 Anthropic Messages API。"""
    import anthropic

    client_kwargs: dict[str, Any] = {"api_key": api_key}
    if config.base_url:
        client_kwargs["base_url"] = config.base_url
    client = anthropic.Anthropic(**client_kwargs)

    messages: list[dict[str, Any]] = []
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    try:
        response = client.messages.create(
            model=model_id,
            max_tokens=config.max_tokens,
            system=config.system_prompt,
            messages=messages,
        )
        # 提取文本内容
        text_parts = []
        for block in response.content:
            if hasattr(block, "text"):
                text_parts.append(block.text)
        return "\n".join(text_parts) if text_parts else "(Agent 无文本输出)"
    except anthropic.APIError as exc:
        raise RuntimeError(f"Anthropic API 错误: {exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"调用失败: {exc}") from exc


def _call_openai_compatible(
    api_key: str,
    model_id: str,
    config: AgentConfig,
    user_message: str,
    history: list[dict[str, str]] | None,
) -> str:
    """调用 OpenAI 兼容 API（支持 DeepSeek、GPT、Gemini 等）。"""
    try:
        import openai
    except ImportError:
        raise RuntimeError("需要安装 openai 包: pip install openai")

    # 根据模型选择 base_url（用户自定义优先）
    base_url = config.base_url or None
    if not base_url:
        if model_id.startswith("deepseek"):
            base_url = "https://api.deepseek.com/v1"
        elif model_id.startswith("gemini"):
            base_url = "https://generativelanguage.googleapis.com/v1beta/openai"

    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url

    client = openai.OpenAI(**client_kwargs)

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": config.system_prompt},
    ]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    try:
        response = client.chat.completions.create(
            model=model_id,
            max_tokens=config.max_tokens,
            temperature=config.temperature,
            messages=messages,
        )
        return response.choices[0].message.content or "(Agent 无文本输出)"
    except Exception as exc:
        raise RuntimeError(f"API 调用失败 ({model_id}): {exc}") from exc
