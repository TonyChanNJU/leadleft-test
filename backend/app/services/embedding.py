"""BGE-M3 embedding service with cloud (SiliconFlow) and local mode support.

Cloud mode: Uses SiliconFlow API (OpenAI-compatible) — no local resources needed.
Local mode: Uses sentence-transformers to load BGE-M3 locally — needs ~2GB RAM.
"""

from typing import Optional

from llama_index.core.embeddings import BaseEmbedding
from pydantic import PrivateAttr

_EMBED_MODEL_CACHE: dict[str, BaseEmbedding] = {}


def reset_embedding_cache() -> None:
    """Clear any cached embedding model instances (used after destructive wipes)."""
    _EMBED_MODEL_CACHE.clear()


class SiliconFlowEmbedding(BaseEmbedding):
    """BGE-M3 embedding via SiliconFlow cloud API (OpenAI-compatible)."""

    _api_key: str = PrivateAttr()
    _base_url: str = PrivateAttr(default="https://api.siliconflow.cn/v1")
    _model_name: str = PrivateAttr(default="BAAI/bge-m3")
    _client: Optional[object] = PrivateAttr(default=None)

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.siliconflow.cn/v1",
        model_name: str = "BAAI/bge-m3",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._api_key = api_key
        self._base_url = base_url
        self._model_name = model_name
        self._client = None

    def _get_client(self):
        """Lazily initialize the OpenAI client for SiliconFlow."""
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(
                api_key=self._api_key,
                base_url=self._base_url,
            )
        return self._client

    def _get_text_embedding(self, text: str) -> list[float]:
        """Get embedding for a single text."""
        client = self._get_client()
        response = client.embeddings.create(
            model=self._model_name,
            input=[text],
        )
        return response.data[0].embedding

    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Get embeddings for multiple texts (batch)."""
        client = self._get_client()
        # SiliconFlow supports batch embedding
        response = client.embeddings.create(
            model=self._model_name,
            input=texts,
        )
        # Sort by index to maintain order
        sorted_data = sorted(response.data, key=lambda x: x.index)
        return [d.embedding for d in sorted_data]

    async def _aget_text_embedding(self, text: str) -> list[float]:
        """Async version — falls back to sync for now."""
        return self._get_text_embedding(text)

    async def _aget_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Async batch version — falls back to sync for now."""
        return self._get_text_embeddings(texts)

    def _get_query_embedding(self, query: str) -> list[float]:
        """Get embedding for a query."""
        return self._get_text_embedding(query)

    async def _aget_query_embedding(self, query: str) -> list[float]:
        """Async get embedding for a query."""
        return self._get_text_embedding(query)


def get_embedding_model(
    provider: str = "cloud",
    api_key: Optional[str] = None,
) -> BaseEmbedding:
    """Factory function to create the appropriate embedding model.
    
    Args:
        provider: "cloud" for SiliconFlow API, "local" for local model.
        api_key: SiliconFlow API key (required for cloud mode).
        
    Returns:
        A LlamaIndex-compatible embedding model.
        
    Raises:
        ValueError: If cloud mode is selected but no API key provided.
    """
    cache_key = f"{provider}:{api_key or ''}"
    cached = _EMBED_MODEL_CACHE.get(cache_key)
    if cached is not None:
        return cached

    if provider == "cloud":
        if not api_key:
            raise ValueError(
                "SiliconFlow API key required for cloud embedding. "
                "Set SILICONFLOW_API_KEY in .env"
            )
        model: BaseEmbedding = SiliconFlowEmbedding(api_key=api_key)
        _EMBED_MODEL_CACHE[cache_key] = model
        return model

    elif provider == "local":
        # Use HuggingFace embedding from LlamaIndex
        from llama_index.embeddings.huggingface import HuggingFaceEmbedding
        model = HuggingFaceEmbedding(
            model_name="BAAI/bge-m3",
            trust_remote_code=True,
        )
        _EMBED_MODEL_CACHE[cache_key] = model
        return model

    else:
        raise ValueError(f"Unknown embedding provider: {provider}")
