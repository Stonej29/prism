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
        parsed = _parse_json_object(content)
        return LLMGeneration(data=parsed, model=str(data.get("model") or self.config.model))

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

    def answer_question(self, context: dict[str, Any]) -> str:
        if not self.config.is_configured:
            raise RuntimeError("LLM_API_KEY and LLM_MODEL are required")
        payload: dict[str, Any] = {
            "model": self.config.model,
            "temperature": 0.2,
            "max_tokens": 1200,
            "messages": [
                {"role": "system", "content": _ask_system_prompt()},
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
                {"role": "system", "content": _profile_system_prompt(mode)},
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
        with httpx.Client(timeout=httpx.Timeout(LLM_TIMEOUT_SECONDS)) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            return response.json()

    def _payload(self, context: dict[str, Any], profile: str, use_response_format: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "temperature": 0.2,
            "max_tokens": 4500,
            "messages": [
                {"role": "system", "content": _system_prompt()},
                {"role": "user", "content": json.dumps({"profile": profile, "source": context}, ensure_ascii=True)},
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
                {"role": "system", "content": _idea_system_prompt()},
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
) -> dict[str, Any]:
    return {
        "topic": topic or None,
        "knowledge": knowledge,
        "past_rated_ideas": past_ideas,
    }


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
        "actionability, interest, overall, confidence, related_notes. Scores are numeric 1-10. "
        "related_notes must be a list of objects with id, title, and reason selected only from related_candidates. "
        "Use direct language, preserve uncertainty, and favor a healthy mix of "
        "buildable ideas, research novelty, and practical tool value."
    )


def _idea_system_prompt() -> str:
    return (
        "You are PRISM's idea engine. Generate one concrete, buildable project idea "
        "synthesized from the user's saved knowledge and profile. "
        "Return only a valid JSON object with fields: title, summary, problem, approach, "
        "why_it_fits, components, risks, related_notes, tags. "
        "components, risks, and tags are lists of strings. "
        "related_notes is a list of objects with id, title, and reason, selected only from "
        "context.knowledge entries (use their exact ids). "
        "summary is a single punchy sentence pitching the idea. "
        "If context.past_rated_ideas is provided, prefer directions similar to highly rated "
        "ideas and avoid those that rated poorly. "
        "Be specific and technical, ground the idea in the provided notes, and favor things "
        "the user could actually build."
    )


def _profile_system_prompt(mode: str) -> str:
    base = (
        "You maintain PRISM's personal profile file at profile/personal.md. "
        "Return only Markdown, with no code fence and no commentary. "
        "Use this exact structure: # Personal Profile, then short sections for Context, "
        "Interests, Preferences, Constraints, and Current Direction. "
        "Keep it concise, concrete, and useful for steering research-note summaries and idea generation. "
        "Preserve specific facts, tools, projects, locations, and preferences. Do not invent details."
    )
    if mode == "reset":
        return base + " Replace the profile completely using only the user's new input."
    return base + " Update the existing profile by integrating the user's new input without losing still-relevant existing facts."


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


def _ask_system_prompt() -> str:
    return (
        "You answer the user's question using ONLY the notes provided in context.notes, "
        "which come from their personal research vault. Do not use outside knowledge and "
        "never invent facts. If the notes do not contain the answer, say plainly that you "
        "have nothing saved about it. Cite the note ids you rely on in square brackets, "
        "e.g. [a1b2c3]. Be concise, direct, and technical."
    )
