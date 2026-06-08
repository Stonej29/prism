from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from prism import settings_store
from prism.config import load_settings


class ConfigOverrideTest(unittest.TestCase):
    def _env(self, tmp: str, **extra: str) -> dict[str, str]:
        env = {
            "SQLITE_PATH": str(Path(tmp) / "prism.sqlite3"),
            "PRISM_CONFIG_FILE": str(Path(tmp) / "settings.json"),
            "LLM_API_KEY": "", "LLM_MODEL": "", "LLM_BASE_URL": "",
            "EMBEDDING_API_KEY": "", "EMBEDDING_MODEL": "", "EMBEDDING_BASE_URL": "",
            "TELEGRAM_BOT_TOKEN": "", "TELEGRAM_ALLOWED_USER_IDS": "",
        }
        env.update(extra)
        return env

    def test_store_overrides_apply_and_env_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict("os.environ", self._env(tmp)):
                s = load_settings(require_telegram=False)
                self.assertIsNone(s.llm_api_key)
                self.assertEqual(s.llm_base_url, "https://openrouter.ai/api/v1")

                settings_store.save_overrides(
                    {"llm_api_key": "sk-store", "llm_model": "m", "llm_base_url": "https://s/v1"}
                )
                self.assertEqual(oct((Path(tmp) / "settings.json").stat().st_mode)[-3:], "600")
                s = load_settings(require_telegram=False)
                self.assertEqual(s.llm_api_key, "sk-store")
                self.assertEqual(s.llm_model, "m")
                self.assertEqual(s.llm_base_url, "https://s/v1")
                self.assertEqual(settings_store.field_source("llm_api_key"), "store")

            # Env wins over the store and locks the field.
            with patch.dict("os.environ", self._env(tmp, LLM_API_KEY="sk-env")):
                s = load_settings(require_telegram=False)
                self.assertEqual(s.llm_api_key, "sk-env")
                self.assertEqual(s.llm_model, "m")  # still from the store
                self.assertTrue(settings_store.is_env_locked("llm_api_key"))
                self.assertEqual(settings_store.field_source("llm_api_key"), "env")

    def test_clearing_and_unknown_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict("os.environ", self._env(tmp)):
                settings_store.save_overrides({"llm_model": "m", "bogus": "x"})
                self.assertEqual(settings_store.load_overrides(), {"llm_model": "m"})
                settings_store.save_overrides({"llm_model": ""})
                self.assertEqual(settings_store.load_overrides(), {})

    def test_missing_store_is_tolerated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict("os.environ", self._env(tmp)):
                self.assertEqual(settings_store.load_overrides(), {})
                load_settings(require_telegram=False)  # must not raise

    def test_telegram_from_store_satisfies_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict("os.environ", self._env(tmp)):
                with self.assertRaises(RuntimeError):
                    load_settings(require_telegram=True)
                settings_store.save_overrides(
                    {"telegram_bot_token": "abc", "telegram_allowed_user_ids": "1,2"}
                )
                s = load_settings(require_telegram=True)
                self.assertEqual(s.telegram_bot_token, "abc")
                self.assertEqual(s.telegram_allowed_user_ids, frozenset({1, 2}))


if __name__ == "__main__":
    unittest.main()
