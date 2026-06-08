from __future__ import annotations

import unittest

from prism import prompts


class PromptTests(unittest.TestCase):
    def test_note_prompt_includes_scoring_rubric(self) -> None:
        prompt = prompts.note_system_prompt()

        self.assertIn("Return only a valid JSON object", prompt)
        self.assertIn("SCORING:", prompt)
        self.assertNotIn("{{SCORING_RUBRIC}}", prompt)

    def test_personalize_prompt_expands_rubric_and_targets_personal_fields(self) -> None:
        prompt = prompts.personalize_system_prompt()

        self.assertIn("Return only a valid JSON object", prompt)
        self.assertIn("personal_relevance", prompt)
        self.assertIn("SCORING:", prompt)
        self.assertNotIn("{{SCORING_RUBRIC}}", prompt)

    def test_ground_truth_prompt_omits_personal_fields(self) -> None:
        prompt = prompts.note_system_prompt()
        # Personal fields are produced by the separate personalization pass, not here.
        self.assertNotIn("personal_relevance", prompt)

    def test_profile_prompt_modes_are_expanded(self) -> None:
        reset = prompts.profile_system_prompt("reset")
        update = prompts.profile_system_prompt("update")

        self.assertIn("Replace the profile completely", reset)
        self.assertIn("Update the existing profile", update)
        self.assertNotIn("{{MODE_INSTRUCTION}}", reset)
        self.assertNotIn("{{MODE_INSTRUCTION}}", update)

    def test_profile_prompt_rejects_unknown_mode(self) -> None:
        with self.assertRaises(ValueError):
            prompts.profile_system_prompt("bad")


if __name__ == "__main__":
    unittest.main()
