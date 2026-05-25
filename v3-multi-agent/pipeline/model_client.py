"""
统一 LLM 客户端 — 工厂模式封装多模型调用

支持 DeepSeek、Qwen、OpenAI，通过环境变量切换。
返回统一格式：{"content": str, "usage": {"prompt_tokens": int, "completion_tokens": int}}
"""

from __future__ import annotations

import os
import time
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ── 数据结构 ──────────────────────────────────────────────────────────────

@dataclass
class Usage:
    """Token 用量统计"""
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def to_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass
class LLMResponse:
    """统一的 LLM 响应格式"""
    content: str
    usage: Usage = field(default_factory=Usage)

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "usage": self.usage.to_dict(),
        }


# ── 成本估算（每 1K tokens 价格，单位 USD） ────────────────────────────────
#价格定义    这里需要实时根据最新消息修改
PRICING: dict[str, dict[str, float]] = {
    "deepseek-chat": {"input": 0.0014, "output": 0.0028},
    "deepseek-reasoner": {"input": 0.004, "output": 0.016},
    "qwen-plus": {"input": 0.002, "output": 0.006},
    "qwen-turbo": {"input": 0.0005, "output": 0.001},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gpt-4o": {"input": 0.005, "output": 0.015},
}


def estimate_cost(model: str, usage: Usage) -> float:
    """估算单次调用成本（USD）"""
    prices = PRICING.get(model, {"input": 0.002, "output": 0.006})
    return (
        usage.prompt_tokens / 1000 * prices["input"]
        + usage.completion_tokens / 1000 * prices["output"]
    )


# ── Provider 抽象基类 ────────────────────────────────────────────────────

class LLMProvider(ABC):
    """LLM 提供商抽象基类"""

    def __init__(self, api_key: str, base_url: str, model: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.client = httpx.Client(timeout=60.0)

    @abstractmethod
    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> LLMResponse:
        """发送聊天请求，返回统一格式响应"""
        ...

    def close(self) -> None:
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class OpenAICompatibleProvider(LLMProvider):
    """
    兼容 OpenAI Chat Completions API 的提供商。
    DeepSeek、Qwen、OpenAI 都使用相同的 API 格式。
    """

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> LLMResponse:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        resp = self.client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        content = data["choices"][0]["message"]["content"]
        usage_data = data.get("usage", {})
        usage = Usage(
            prompt_tokens=usage_data.get("prompt_tokens", 0),
            completion_tokens=usage_data.get("completion_tokens", 0),
        )

        return LLMResponse(content=content, usage=usage)


# ── 工厂函数 ─────────────────────────────────────────────────────────────

# 各提供商的环境变量映射
PROVIDER_CONFIG: dict[str, dict[str, str]] = {
    "deepseek": {
        "api_key_env": "DEEPSEEK_API_KEY",
        "base_url_env": "DEEPSEEK_BASE_URL",
        "model_env": "DEEPSEEK_MODEL",
        "default_base_url": "https://api.deepseek.com",
        "default_model": "deepseek-v4-pro",
    },
    "qwen": {
        "api_key_env": "QWEN_API_KEY",
        "base_url_env": "QWEN_BASE_URL",
        "model_env": "QWEN_MODEL",
        "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-plus",
    },
    "openai": {
        "api_key_env": "OPENAI_API_KEY",
        "base_url_env": "OPENAI_BASE_URL",
        "model_env": "OPENAI_MODEL",
        "default_base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
    },
}


def create_provider(provider_name: str | None = None) -> LLMProvider:
    """
    工厂函数：根据提供商名称创建对应的 LLM 客户端。

    Args:
        provider_name: 提供商名称（deepseek/qwen/openai），
                       默认读取环境变量 LLM_PROVIDER

    Returns:
        LLMProvider 实例

    Raises:
        ValueError: 未知的提供商名称
        RuntimeError: 缺少 API Key
    """
    name = (provider_name or os.getenv("LLM_PROVIDER", "deepseek")).lower()

    if name not in PROVIDER_CONFIG:
        raise ValueError(
            f"未知的模型提供商: {name}，支持: {', '.join(PROVIDER_CONFIG.keys())}"
        )

    config = PROVIDER_CONFIG[name]
    api_key = os.getenv(config["api_key_env"], "")
    if not api_key:
        raise RuntimeError(
            f"缺少 API Key，请设置环境变量: {config['api_key_env']}"
        )

    base_url = os.getenv(config["base_url_env"], config["default_base_url"])
    model = os.getenv(config["model_env"], config["default_model"])

    logger.info("创建 LLM 客户端: provider=%s, model=%s", name, model)
    return OpenAICompatibleProvider(api_key=api_key, base_url=base_url, model=model)


# ── 带重试的调用封装 ──────────────────────────────────────────────────────

def chat_with_retry(
    provider: LLMProvider,
    messages: list[dict[str, str]],
    temperature: float = 0.7,
    max_tokens: int = 2000,
    max_retries: int = 3,
    backoff_base: float = 2.0,
) -> LLMResponse:
    """
    带指数退避重试的聊天调用。

    Args:
        provider: LLM 提供商实例
        messages: 消息列表
        temperature: 温度参数
        max_tokens: 最大生成 token 数
        max_retries: 最大重试次数
        backoff_base: 退避基数（秒）

    Returns:
        LLMResponse 统一响应

    Raises:
        最后一次重试仍失败时抛出原始异常
    """
    last_error: Exception | None = None

    for attempt in range(max_retries):
        try:
            response = provider.chat(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            if attempt > 0:
                logger.info("第 %d 次重试成功", attempt)
            return response

        except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException) as e:
            last_error = e
            if attempt < max_retries - 1:
                wait_time = backoff_base ** attempt
                logger.warning(
                    "LLM 调用失败（第 %d/%d 次），%0.1f 秒后重试: %s",
                    attempt + 1, max_retries, wait_time, str(e),
                )
                time.sleep(wait_time)
            else:
                logger.error("LLM 调用失败，已达最大重试次数: %s", str(e))

    raise last_error  # type: ignore[misc]


# ── 便捷函数 ─────────────────────────────────────────────────────────────

def quick_chat(
    prompt: str,
    system: str = "你是一个 AI 技术分析助手。",
    provider_name: str | None = None,
) -> str:
    """
    快捷调用：一句话调用 LLM，返回纯文本。

    Args:
        prompt: 用户提示词
        system: 系统提示词
        provider_name: 提供商名称，默认读环境变量

    Returns:
        LLM 返回的文本内容
    """
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]

    provider = create_provider(provider_name)
    try:
        response = chat_with_retry(provider, messages)
        cost = estimate_cost(provider.model, response.usage)
        logger.info(
            "Token 用量: %d (prompt) + %d (completion) = %d, 估算成本: $%.6f",
            response.usage.prompt_tokens,
            response.usage.completion_tokens,
            response.usage.total_tokens,
            cost,
        )
        return response.content
    finally:
        provider.close()


# ── CLI 测试入口 ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    print("=== LLM 客户端测试 ===")
    print(f"提供商: {os.getenv('LLM_PROVIDER', 'deepseek')}")

    try:
        result = quick_chat("用一句话介绍什么是 AI Agent。")
        print(f"\n回复: {result}")
    except Exception as e:
        print(f"\n错误: {e}")
        print("请检查 .env 文件中的 API Key 配置。")
