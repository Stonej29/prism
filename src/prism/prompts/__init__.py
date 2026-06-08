from __future__ import annotations

from importlib import resources


def _read_prompt(filename: str) -> str:
    return resources.files(__package__).joinpath(filename).read_text(encoding="utf-8").strip()


def _replace_tokens(template: str, replacements: dict[str, str]) -> str:
    prompt = template
    for token, value in replacements.items():
        prompt = prompt.replace(token, value)
    return prompt


def scoring_rubric() -> str:
    return _read_prompt("scoring_rubric.txt")


def note_system_prompt() -> str:
    return _replace_tokens(
        _read_prompt("note_system.txt"),
        {"{{SCORING_RUBRIC}}": scoring_rubric()},
    )


def idea_system_prompt() -> str:
    return _read_prompt("idea_system.txt")


def merge_system_prompt() -> str:
    return _replace_tokens(
        _read_prompt("merge_system.txt"),
        {"{{SCORING_RUBRIC}}": scoring_rubric()},
    )


def profile_system_prompt(mode: str) -> str:
    if mode == "reset":
        mode_instruction = "Replace the profile completely using only the user's new input."
    elif mode == "update":
        mode_instruction = (
            "Update the existing profile by integrating the user's new input without losing "
            "still-relevant existing facts."
        )
    else:
        raise ValueError("mode must be reset or update")

    return _replace_tokens(
        _read_prompt("profile_system.txt"),
        {"{{MODE_INSTRUCTION}}": mode_instruction},
    )


def ask_system_prompt() -> str:
    return _read_prompt("ask_system.txt")
