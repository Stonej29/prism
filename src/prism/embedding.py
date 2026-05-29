from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

EMBEDDING_TIMEOUT_SECONDS = 60.0


@dataclass(frozen=True)
class EmbeddingConfig:
    base_url: str = "https://api.openai.com/v1"
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
        with httpx.Client(timeout=httpx.Timeout(EMBEDDING_TIMEOUT_SECONDS)) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        vector = _first_embedding(data)
        model = str(data.get("model") or self.config.model)
        return EmbeddingResult(vector=vector, model=model)


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
