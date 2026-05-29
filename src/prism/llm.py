from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

LLM_TIMEOUT_SECONDS = 90.0
SOURCE_TEXT_LIMIT = 60000


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    api_key: str | None
    model: str | None

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.model)


@dataclass(frozen=True)
class LLMGeneration:
    data: dict[str, Any]
    model: str


class LLMClient:
    def __init__(self, config: LLMConfig) -> None:
        self.config = config

    def generate_note(self, context: dict[str, Any], profile: str) -> LLMGeneration:
        if not self.config.is_configured:
            raise RuntimeError("LLM_API_KEY and LLM_MODEL are required")

        payload = self._payload(context, profile, use_response_format=True)
        try:
            data = self._post(payload)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 400:
                data = self._post(self._payload(context, profile, use_response_format=False))
            else:
                raise

        content = _assistant_content(data)
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError("LLM response JSON was not an object")
        return LLMGeneration(data=parsed, model=str(data.get("model") or self.config.model))

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        assert self.config.api_key is not None
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=httpx.Timeout(LLM_TIMEOUT_SECONDS)) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            return response.json()

    def _payload(self, context: dict[str, Any], profile: str, use_response_format: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "temperature": 0.2,
            "max_tokens": 2500,
            "messages": [
                {"role": "system", "content": _system_prompt()},
                {"role": "user", "content": json.dumps({"profile": profile, "source": context}, ensure_ascii=True)},
            ],
        }
        if use_response_format:
            payload["response_format"] = {"type": "json_object"}
        return payload


def build_llm_context(
    *,
    title: str,
    source_kind: str,
    source_url: str,
    resolved_url: str,
    fetched_at: str | None,
    fetch_status: str,
    fetch_error: str | None,
    metadata: dict[str, Any],
    extracted_text: str,
) -> dict[str, Any]:
    return {
        "title": title,
        "source_kind": source_kind,
        "source_url": source_url,
        "resolved_url": resolved_url,
        "fetched_at": fetched_at,
        "fetch_status": fetch_status,
        "fetch_error": fetch_error,
        "metadata": metadata,
        "extracted_text_truncated_to_chars": SOURCE_TEXT_LIMIT,
        "extracted_text": extracted_text[:SOURCE_TEXT_LIMIT],
    }


def _assistant_content(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("LLM response did not contain choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise ValueError("LLM response did not contain message content")
    return content


def _system_prompt() -> str:
    return (
        "You generate dense, practical, technical Obsidian notes for PRISM. "
        "Return only a valid JSON object. Required fields: title, quick_summary, "
        "detailed_summary, key_claims, limitations, technical_details, why_it_matters, "
        "personal_relevance, project_ideas, tags, relevance, novelty, credibility, "
        "actionability, interest, overall, confidence. Scores are numeric 1-10. "
        "Use direct language, preserve uncertainty, and favor a healthy mix of "
        "buildable ideas, research novelty, and practical tool value."
    )
