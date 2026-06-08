from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from prism.config import DEFAULT_EMBEDDING_BASE_URL
from prism.usage import record_usage

LOGGER = logging.getLogger("prism.embedding")

EMBEDDING_TIMEOUT_SECONDS = 60.0

# Bounded retry for transient failures (timeouts, connection resets, 5xx).
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_BASE = 1.0
_RETRYABLE = (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError, httpx.WriteError, httpx.PoolTimeout)


@dataclass(frozen=True)
class EmbeddingConfig:
    base_url: str = DEFAULT_EMBEDDING_BASE_URL
    api_key: str | None = None
    model: str | None = None

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.model)


@dataclass(frozen=True)
class EmbeddingResult:
    vector: list[float]
    model: str

    @property
    def dimensions(self) -> int:
        return len(self.vector)


class EmbeddingClient:
    def __init__(self, config: EmbeddingConfig) -> None:
        self.config = config

    def embed(self, text: str) -> EmbeddingResult:
        if not self.config.is_configured:
            raise RuntimeError("EMBEDDING_API_KEY and EMBEDDING_MODEL are required")
        if not text.strip():
            raise ValueError("embedding input must not be empty")

        assert self.config.api_key is not None
        url = self.config.base_url.rstrip("/") + "/embeddings"
        payload = {"model": self.config.model, "input": text}
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        data = self._post(url, headers, payload)
        vector = _first_embedding(data)
        model = str(data.get("model") or self.config.model)
        return EmbeddingResult(vector=vector, model=model)

    def _post(self, url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(RETRY_ATTEMPTS):
            try:
                with httpx.Client(timeout=httpx.Timeout(EMBEDDING_TIMEOUT_SECONDS)) as client:
                    response = client.post(url, headers=headers, json=payload)
                    response.raise_for_status()
                    data = response.json()
                usage = data.get("usage")
                if isinstance(usage, dict):
                    LOGGER.info(
                        "embedding usage model=%s prompt=%s total=%s",
                        data.get("model") or self.config.model,
                        usage.get("prompt_tokens"), usage.get("total_tokens"),
                    )
                    record_usage("embedding", usage.get("prompt_tokens"), 0, usage.get("total_tokens"))
                return data
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code < 500 or attempt == RETRY_ATTEMPTS - 1:
                    raise
                last_exc = exc
            except _RETRYABLE as exc:
                if attempt == RETRY_ATTEMPTS - 1:
                    raise
                last_exc = exc
            LOGGER.warning("embedding request failed (%s); retry %d/%d", type(last_exc).__name__, attempt + 1, RETRY_ATTEMPTS - 1)
            time.sleep(RETRY_BACKOFF_BASE * (2 ** attempt))
        raise last_exc  # pragma: no cover - loop either returns or raises


def _first_embedding(data: dict[str, Any]) -> list[float]:
    items = data.get("data")
    if not isinstance(items, list) or not items:
        raise ValueError("embedding response did not contain data")
    embedding = items[0].get("embedding") if isinstance(items[0], dict) else None
    if not isinstance(embedding, list) or not embedding:
        raise ValueError("embedding response did not contain a vector")
    vector: list[float] = []
    for item in embedding:
        if not isinstance(item, (int, float)) or isinstance(item, bool):
            raise ValueError("embedding vector contained a non-numeric value")
        vector.append(float(item))
    return vector
