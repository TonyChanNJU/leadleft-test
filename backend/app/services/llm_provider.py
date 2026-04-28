"""Multi-LLM provider adapter.

Unified interface for GPT, Claude, Gemini, and DeepSeek using official SDKs.
No LiteLLM dependency — direct SDK calls for security.
"""

import logging
from abc import ABC, abstractmethod
from typing import Generator, Optional

import time
import uuid

from llama_index.core.llms import (
    CustomLLM,
    ChatMessage,
    ChatResponse,
    CompletionResponse,
    MessageRole,
)
from llama_index.core.llms.callbacks import llm_chat_callback, llm_completion_callback
from pydantic import PrivateAttr

logger = logging.getLogger(__name__)


# ============================================================
# Supported models registry
# ============================================================

SUPPORTED_MODELS = {
    # OpenAI
    "gpt-4o": {"provider": "openai", "display": "GPT-4o"},
    "gpt-4o-mini": {"provider": "openai", "display": "GPT-4o Mini"},
    "gpt-4-turbo": {"provider": "openai", "display": "GPT-4 Turbo"},
    # Anthropic
    "claude-3-5-sonnet-20241022": {"provider": "anthropic", "display": "Claude 3.5 Sonnet"},
    "claude-3-opus-20240229": {"provider": "anthropic", "display": "Claude 3 Opus"},
    "claude-sonnet-4-20250514": {"provider": "anthropic", "display": "Claude Sonnet 4"},
    # Google Gemini
    "gemini-2.0-flash": {"provider": "google", "display": "Gemini 2.0 Flash"},
    "gemini-2.5-flash-preview-04-17": {"provider": "google", "display": "Gemini 2.5 Flash"},
    "gemini-2.5-pro-preview-03-25": {"provider": "google", "display": "Gemini 2.5 Pro"},
    # DeepSeek (OpenAI-compatible)
    "deepseek-chat": {"provider": "deepseek", "display": "DeepSeek-V3"},
    "deepseek-reasoner": {"provider": "deepseek", "display": "DeepSeek-R1"},
    # DeepSeek V4 (Preview)
    "deepseek-v4-pro": {"provider": "deepseek", "display": "DeepSeek V4 Pro"},
    "deepseek-v4-flash": {"provider": "deepseek", "display": "DeepSeek V4 Flash"},
}


def get_available_models(api_keys: dict) -> list[dict]:
    """Return models that have valid API keys configured.
    
    Args:
        api_keys: Dict mapping provider names to API keys.
        
    Returns:
        List of available model info dicts.
    """
    available = []
    provider_key_map = {
        "openai": "openai",
        "anthropic": "anthropic",
        "google": "google",
        "deepseek": "deepseek",
    }

    for model_id, info in SUPPORTED_MODELS.items():
        provider = info["provider"]
        key_name = provider_key_map.get(provider)
        if key_name and api_keys.get(key_name):
            available.append({
                "model_id": model_id,
                "provider": provider,
                "display": info["display"],
            })

    return available


# ============================================================
# LlamaIndex-compatible LLM wrappers
# ============================================================

class OpenAILLM(CustomLLM):
    """OpenAI LLM wrapper using official SDK."""

    model: str = "gpt-4o"
    temperature: float = 0.1
    _api_key: str = PrivateAttr()
    _base_url: Optional[str] = PrivateAttr(default=None)
    _client: Optional[object] = PrivateAttr(default=None)

    def __init__(self, api_key: str, model: str = "gpt-4o", base_url: Optional[str] = None, **kwargs):
        super().__init__(model=model, **kwargs)
        self._api_key = api_key
        self._base_url = base_url
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI
            kwargs = {"api_key": self._api_key}
            if self._base_url:
                kwargs["base_url"] = self._base_url
            self._client = OpenAI(**kwargs)
        return self._client

    @property
    def metadata(self):
        from llama_index.core.llms import LLMMetadata
        return LLMMetadata(model_name=self.model)

    @llm_chat_callback()
    def chat(self, messages: list[ChatMessage], **kwargs) -> ChatResponse:
        request_id = uuid.uuid4().hex[:12]
        t0 = time.perf_counter()
        client = self._get_client()
        openai_messages = [
            {"role": m.role.value, "content": m.content} for m in messages
        ]
        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=openai_messages,
                temperature=self.temperature,
            )
            content = response.choices[0].message.content or ""
            dt_ms = int((time.perf_counter() - t0) * 1000)
            logger.info(
                "LLM chat OK provider=%s model=%s request_id=%s duration_ms=%s",
                "openai",
                self.model,
                request_id,
                dt_ms,
            )
        except Exception:
            dt_ms = int((time.perf_counter() - t0) * 1000)
            logger.exception(
                "LLM chat FAIL provider=%s model=%s request_id=%s duration_ms=%s",
                "openai",
                self.model,
                request_id,
                dt_ms,
            )
            raise
        return ChatResponse(
            message=ChatMessage(role=MessageRole.ASSISTANT, content=content)
        )

    @llm_completion_callback()
    def complete(self, prompt: str, **kwargs) -> CompletionResponse:
        response = self.chat([ChatMessage(role=MessageRole.USER, content=prompt)])
        return CompletionResponse(text=response.message.content)

    def stream_chat(self, messages: list[ChatMessage], **kwargs):
        client = self._get_client()
        openai_messages = [
            {"role": m.role.value, "content": m.content} for m in messages
        ]
        stream = client.chat.completions.create(
            model=self.model,
            messages=openai_messages,
            temperature=self.temperature,
            stream=True,
        )
        full_content = ""
        for chunk in stream:
            delta = chunk.choices[0].delta.content or ""
            full_content += delta
            yield ChatResponse(
                message=ChatMessage(role=MessageRole.ASSISTANT, content=full_content),
                delta=delta,
            )

    def stream_complete(self, prompt: str, **kwargs):
        for response in self.stream_chat([ChatMessage(role=MessageRole.USER, content=prompt)]):
            yield CompletionResponse(text=response.message.content, delta=response.delta)


class AnthropicLLM(CustomLLM):
    """Anthropic Claude LLM wrapper using official SDK."""

    model: str = "claude-3-5-sonnet-20241022"
    temperature: float = 0.1
    max_tokens: int = 4096
    _api_key: str = PrivateAttr()
    _client: Optional[object] = PrivateAttr(default=None)

    def __init__(self, api_key: str, model: str = "claude-3-5-sonnet-20241022", **kwargs):
        super().__init__(model=model, **kwargs)
        self._api_key = api_key
        self._client = None

    def _get_client(self):
        if self._client is None:
            from anthropic import Anthropic
            self._client = Anthropic(api_key=self._api_key)
        return self._client

    @property
    def metadata(self):
        from llama_index.core.llms import LLMMetadata
        return LLMMetadata(model_name=self.model)

    @llm_chat_callback()
    def chat(self, messages: list[ChatMessage], **kwargs) -> ChatResponse:
        request_id = uuid.uuid4().hex[:12]
        t0 = time.perf_counter()
        client = self._get_client()
        # Anthropic requires system message separate from user messages
        system_msg = ""
        chat_messages = []
        for m in messages:
            if m.role == MessageRole.SYSTEM:
                system_msg = m.content
            else:
                chat_messages.append({"role": m.role.value, "content": m.content})

        create_kwargs = {
            "model": self.model,
            "messages": chat_messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }
        if system_msg:
            create_kwargs["system"] = system_msg

        try:
            response = client.messages.create(**create_kwargs)
            content = response.content[0].text if response.content else ""
            dt_ms = int((time.perf_counter() - t0) * 1000)
            logger.info(
                "LLM chat OK provider=%s model=%s request_id=%s duration_ms=%s",
                "anthropic",
                self.model,
                request_id,
                dt_ms,
            )
        except Exception:
            dt_ms = int((time.perf_counter() - t0) * 1000)
            logger.exception(
                "LLM chat FAIL provider=%s model=%s request_id=%s duration_ms=%s",
                "anthropic",
                self.model,
                request_id,
                dt_ms,
            )
            raise
        return ChatResponse(
            message=ChatMessage(role=MessageRole.ASSISTANT, content=content)
        )

    @llm_completion_callback()
    def complete(self, prompt: str, **kwargs) -> CompletionResponse:
        response = self.chat([ChatMessage(role=MessageRole.USER, content=prompt)])
        return CompletionResponse(text=response.message.content)

    def stream_chat(self, messages: list[ChatMessage], **kwargs):
        client = self._get_client()
        system_msg = ""
        chat_messages = []
        for m in messages:
            if m.role == MessageRole.SYSTEM:
                system_msg = m.content
            else:
                chat_messages.append({"role": m.role.value, "content": m.content})

        create_kwargs = {
            "model": self.model,
            "messages": chat_messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }
        if system_msg:
            create_kwargs["system"] = system_msg

        full_content = ""
        with client.messages.stream(**create_kwargs) as stream:
            for text in stream.text_stream:
                full_content += text
                yield ChatResponse(
                    message=ChatMessage(role=MessageRole.ASSISTANT, content=full_content),
                    delta=text,
                )

    def stream_complete(self, prompt: str, **kwargs):
        for response in self.stream_chat([ChatMessage(role=MessageRole.USER, content=prompt)]):
            yield CompletionResponse(text=response.message.content, delta=response.delta)


class GoogleLLM(CustomLLM):
    """Google Gemini LLM wrapper using official SDK."""

    model: str = "gemini-2.0-flash"
    temperature: float = 0.1
    _api_key: str = PrivateAttr()
    _client: Optional[object] = PrivateAttr(default=None)

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash", **kwargs):
        super().__init__(model=model, **kwargs)
        self._api_key = api_key
        self._client = None

    def _get_client(self):
        if self._client is None:
            from google import genai
            self._client = genai.Client(api_key=self._api_key)
        return self._client

    @property
    def metadata(self):
        from llama_index.core.llms import LLMMetadata
        return LLMMetadata(model_name=self.model)

    @llm_chat_callback()
    def chat(self, messages: list[ChatMessage], **kwargs) -> ChatResponse:
        request_id = uuid.uuid4().hex[:12]
        t0 = time.perf_counter()
        client = self._get_client()
        from google.genai import types

        # Convert messages to Gemini format
        system_instruction = None
        gemini_messages = []
        for m in messages:
            if m.role == MessageRole.SYSTEM:
                system_instruction = m.content
            else:
                role = "user" if m.role == MessageRole.USER else "model"
                gemini_messages.append(
                    types.Content(
                        role=role,
                        parts=[types.Part(text=m.content)],
                    )
                )

        config = types.GenerateContentConfig(
            temperature=self.temperature,
        )
        if system_instruction:
            config.system_instruction = system_instruction

        try:
            response = client.models.generate_content(
                model=self.model,
                contents=gemini_messages,
                config=config,
            )
            content = response.text or ""
            dt_ms = int((time.perf_counter() - t0) * 1000)
            logger.info(
                "LLM chat OK provider=%s model=%s request_id=%s duration_ms=%s",
                "google",
                self.model,
                request_id,
                dt_ms,
            )
        except Exception:
            dt_ms = int((time.perf_counter() - t0) * 1000)
            logger.exception(
                "LLM chat FAIL provider=%s model=%s request_id=%s duration_ms=%s",
                "google",
                self.model,
                request_id,
                dt_ms,
            )
            raise
        return ChatResponse(
            message=ChatMessage(role=MessageRole.ASSISTANT, content=content)
        )

    @llm_completion_callback()
    def complete(self, prompt: str, **kwargs) -> CompletionResponse:
        response = self.chat([ChatMessage(role=MessageRole.USER, content=prompt)])
        return CompletionResponse(text=response.message.content)

    def stream_chat(self, messages: list[ChatMessage], **kwargs):
        client = self._get_client()
        from google.genai import types

        system_instruction = None
        gemini_messages = []
        for m in messages:
            if m.role == MessageRole.SYSTEM:
                system_instruction = m.content
            else:
                role = "user" if m.role == MessageRole.USER else "model"
                gemini_messages.append(
                    types.Content(
                        role=role,
                        parts=[types.Part(text=m.content)],
                    )
                )

        config = types.GenerateContentConfig(
            temperature=self.temperature,
        )
        if system_instruction:
            config.system_instruction = system_instruction

        full_content = ""
        stream = client.models.generate_content_stream(
            model=self.model,
            contents=gemini_messages,
            config=config,
        )
        for chunk in stream:
            delta = chunk.text or ""
            full_content += delta
            yield ChatResponse(
                message=ChatMessage(role=MessageRole.ASSISTANT, content=full_content),
                delta=delta,
            )

    def stream_complete(self, prompt: str, **kwargs):
        for response in self.stream_chat([ChatMessage(role=MessageRole.USER, content=prompt)]):
            yield CompletionResponse(text=response.message.content, delta=response.delta)


# ============================================================
# Factory
# ============================================================

def create_llm(model_id: str, api_keys: dict) -> CustomLLM:
    """Create a LlamaIndex-compatible LLM instance.
    
    Args:
        model_id: Model identifier (e.g., "gpt-4o", "claude-3-5-sonnet-20241022").
        api_keys: Dict with provider API keys.
        
    Returns:
        LLM instance ready for use with LlamaIndex.
        
    Raises:
        ValueError: If model is unknown or API key is missing.
    """
    if model_id not in SUPPORTED_MODELS:
        raise ValueError(f"Unknown model: {model_id}. Supported: {list(SUPPORTED_MODELS.keys())}")

    provider = SUPPORTED_MODELS[model_id]["provider"]

    if provider == "openai":
        key = api_keys.get("openai")
        if not key:
            raise ValueError("OPENAI_API_KEY required for OpenAI models")
        return OpenAILLM(api_key=key, model=model_id)

    elif provider == "anthropic":
        key = api_keys.get("anthropic")
        if not key:
            raise ValueError("ANTHROPIC_API_KEY required for Claude models")
        return AnthropicLLM(api_key=key, model=model_id)

    elif provider == "google":
        key = api_keys.get("google")
        if not key:
            raise ValueError("GOOGLE_API_KEY required for Gemini models")
        return GoogleLLM(api_key=key, model=model_id)

    elif provider == "deepseek":
        key = api_keys.get("deepseek")
        if not key:
            raise ValueError("DEEPSEEK_API_KEY required for DeepSeek models")
        return OpenAILLM(
            api_key=key,
            model=model_id,
            base_url="https://api.deepseek.com/v1",
        )

    else:
        raise ValueError(f"Unknown provider: {provider}")
