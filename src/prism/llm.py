from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from prism.prompts import (
    ask_system_prompt,
    idea_system_prompt,
    merge_system_prompt,
    note_system_prompt,
    profile_system_prompt,
)
from prism.usage import record_usage

LOGGER = logging.getLogger("prism.llm")

LLM_TIMEOUT_SECONDS = 90.0
SOURCE_TEXT_LIMIT = 60000

# Bounded retry for transient failures. 4xx (incl. the 400 response_format
# fallback) is never retried so it still propagates to callers.
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_BASE = 1.0
_RETRYABLE = (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError, httpx.WriteError, httpx.PoolTimeout)


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
    web_sources: list[dict[str, str]] = field(default_factory=list)


class LLMClient:
    def __init__(self, config: LLMConfig) -> None:
        self.config = config

    def generate_note(self, context: dict[str, Any], profile: str, *, web: bool = False) -> LLMGeneration:
        if not self.config.is_configured:
            raise RuntimeError("LLM_API_KEY and LLM_MODEL are required")

        try:
            data = self._post(self._payload(context, profile, use_response_format=True, web=web))
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 400:
                raise
            # Progressive 400 fallback: first drop response_format; if the provider
            # still rejects the request, drop the web plugin too (it's the most
            # likely unsupported field) so research degrades to a normal regeneration
            # instead of hard-failing.
            try:
                data = self._post(self._payload(context, profile, use_response_format=False, web=web))
            except httpx.HTTPStatusError as exc2:
                if exc2.response.status_code != 400 or not web:
                    raise
                data = self._post(self._payload(context, profile, use_response_format=False, web=False))

        content = _assistant_content(data)
        parsed = _parse_json_object(content)
        return LLMGeneration(
            data=parsed,
            model=str(data.get("model") or self.config.model),
            web_sources=web_sources_from_response(data),
        )

    def generate_idea(self, context: dict[str, Any], profile: str) -> LLMGeneration:
        if not self.config.is_configured:
            raise RuntimeError("LLM_API_KEY and LLM_MODEL are required")

        payload = self._idea_payload(context, profile, use_response_format=True)
        try:
            data = self._post(payload)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 400:
                data = self._post(self._idea_payload(context, profile, use_response_format=False))
            else:
                raise

        content = _assistant_content(data)
        parsed = _parse_json_object(content)
        return LLMGeneration(data=parsed, model=str(data.get("model") or self.config.model))

    def merge_notes(self, context: dict[str, Any], profile: str) -> LLMGeneration:
        if not self.config.is_configured:
            raise RuntimeError("LLM_API_KEY and LLM_MODEL are required")

        payload = self._merge_payload(context, profile, use_response_format=True)
        try:
            data = self._post(payload)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 400:
                data = self._post(self._merge_payload(context, profile, use_response_format=False))
            else:
                raise

        content = _assistant_content(data)
        parsed = _parse_json_object(content)
        return LLMGeneration(data=parsed, model=str(data.get("model") or self.config.model))

    def answer_question(self, context: dict[str, Any]) -> str:
        if not self.config.is_configured:
            raise RuntimeError("LLM_API_KEY and LLM_MODEL are required")
        payload: dict[str, Any] = {
            "model": self.config.model,
            "temperature": 0.2,
            "max_tokens": 1200,
            "messages": [
                {"role": "system", "content": ask_system_prompt()},
                {"role": "user", "content": json.dumps(context, ensure_ascii=True)},
            ],
        }
        data = self._post(payload)
        return _assistant_content(data).strip()

    def rewrite_profile(self, *, current_profile: str | None, user_input: str, mode: str) -> str:
        if not self.config.is_configured:
            raise RuntimeError("LLM_API_KEY and LLM_MODEL are required")
        if mode not in {"reset", "update"}:
            raise ValueError("mode must be reset or update")
        payload: dict[str, Any] = {
            "model": self.config.model,
            "temperature": 0.2,
            "max_tokens": 1600,
            "messages": [
                {"role": "system", "content": profile_system_prompt(mode)},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"current_profile": current_profile or "", "user_input": user_input},
                        ensure_ascii=True,
                    ),
                },
            ],
        }
        data = self._post(payload)
        return _clean_markdown_profile(_assistant_content(data))

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        assert self.config.api_key is not None
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        last_exc: Exception | None = None
        for attempt in range(RETRY_ATTEMPTS):
            try:
                with httpx.Client(timeout=httpx.Timeout(LLM_TIMEOUT_SECONDS)) as client:
                    response = client.post(url, headers=headers, json=payload)
                    response.raise_for_status()
                    data = response.json()
                _log_usage(data, self.config.model)
                return data
            except httpx.HTTPStatusError as exc:
                # Retry only on server errors; 4xx (incl. the 400 fallback) propagates.
                if exc.response.status_code < 500 or attempt == RETRY_ATTEMPTS - 1:
                    raise
                last_exc = exc
            except _RETRYABLE as exc:
                if attempt == RETRY_ATTEMPTS - 1:
                    raise
                last_exc = exc
            LOGGER.warning("LLM request failed (%s); retry %d/%d", type(last_exc).__name__, attempt + 1, RETRY_ATTEMPTS - 1)
            time.sleep(RETRY_BACKOFF_BASE * (2 ** attempt))
        raise last_exc  # pragma: no cover - loop either returns or raises

    def _payload(self, context: dict[str, Any], profile: str, use_response_format: bool, *, web: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "temperature": 0.2,
            "max_tokens": 4500,
            "messages": [
                {"role": "system", "content": note_system_prompt()},
                {"role": "user", "content": json.dumps({"profile": profile, "source": context}, ensure_ascii=True)},
            ],
        }
        if use_response_format:
            payload["response_format"] = {"type": "json_object"}
        if web:
            payload["plugins"] = [{"id": "web"}]
        return payload

    def _merge_payload(self, context: dict[str, Any], profile: str, use_response_format: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "temperature": 0.2,
            "max_tokens": 4500,
            "messages": [
                {"role": "system", "content": merge_system_prompt()},
                {"role": "user", "content": json.dumps({"profile": profile, "sources": context}, ensure_ascii=True)},
            ],
        }
        if use_response_format:
            payload["response_format"] = {"type": "json_object"}
        return payload

    def _idea_payload(self, context: dict[str, Any], profile: str, use_response_format: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "temperature": 0.7,
            "max_tokens": 2000,
            "messages": [
                {"role": "system", "content": idea_system_prompt()},
                {"role": "user", "content": json.dumps({"profile": profile, "context": context}, ensure_ascii=True)},
            ],
        }
        if use_response_format:
            payload["response_format"] = {"type": "json_object"}
        return payload


def build_idea_context(
    *,
    topic: str | None,
    knowledge: list[dict[str, Any]],
    past_ideas: list[dict[str, Any]],
    recent_ideas: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "topic": topic or None,
        "knowledge": knowledge,
        "past_rated_ideas": past_ideas,
        "recent_ideas": recent_ideas or [],
    }


def build_merge_context(*, notes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return notes


def build_ask_context(*, question: str, notes: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "question": question,
        "notes": notes,
    }


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
    related_candidates: list[dict[str, Any]] | None = None,
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
        "related_candidates": related_candidates or [],
    }


def _parse_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end <= start:
            raise
        parsed = json.loads(text[start:end + 1])

    if not isinstance(parsed, dict):
        raise ValueError("LLM response JSON was not an object")
    return parsed


def _log_usage(data: dict[str, Any], fallback_model: str | None) -> None:
    usage = data.get("usage")
    if isinstance(usage, dict):
        LOGGER.info(
            "LLM usage model=%s prompt=%s completion=%s total=%s",
            data.get("model") or fallback_model,
            usage.get("prompt_tokens"), usage.get("completion_tokens"), usage.get("total_tokens"),
        )
        record_usage("llm", usage.get("prompt_tokens"), usage.get("completion_tokens"), usage.get("total_tokens"))


def web_sources_from_response(response: dict[str, Any]) -> list[dict[str, str]]:
    """Extract the pages the web-search plugin consulted (OpenRouter url_citation
    annotations) so research can show which sources it visited."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return out
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    annotations = message.get("annotations") if isinstance(message, dict) else None
    if not isinstance(annotations, list):
        return out
    for ann in annotations:
        if not isinstance(ann, dict):
            continue
        citation = ann.get("url_citation")
        if not isinstance(citation, dict):
            continue
        url = str(citation.get("url") or "").strip()
        if url and url not in seen:
            seen.add(url)
            out.append({"url": url, "title": str(citation.get("title") or "").strip()})
    return out


def _assistant_content(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("LLM response did not contain choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise ValueError("LLM response did not contain message content")
    return content


def _clean_markdown_profile(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    if not text.startswith("#"):
        text = "# Personal Profile\n\n" + text
    return text.rstrip() + "\n"
