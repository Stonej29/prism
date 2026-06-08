from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from prism import settings_store
from prism.config import DEFAULT_LLM_BASE_URL, load_fetch_settings, load_settings, load_web_settings


class ConfigOverrideTest(unittest.TestCase):
    def _env(self, tmp: str, **extra: str) -> dict[str, str]:
        env = {
            "VAULT_PATH": str(Path(tmp) / "vault"),
            "SQLITE_PATH": str(Path(tmp) / "prism.sqlite3"),
            "ARCHIVE_PATH": str(Path(tmp) / "archives"),
            "LANCEDB_PATH": str(Path(tmp) / "lancedb"),
            "PRISM_CONFIG_FILE": str(Path(tmp) / "settings.json"),
            "LLM_API_KEY": "", "LLM_MODEL": "", "LLM_BASE_URL": "",
            "EMBEDDING_API_KEY": "", "EMBEDDING_MODEL": "", "EMBEDDING_BASE_URL": "",
            "TELEGRAM_BOT_TOKEN": "", "TELEGRAM_ALLOWED_USER_IDS": "",
            "PRISM_WEB_HOST": "", "PRISM_WEB_PORT": "", "PRISM_WEB_RELOAD": "", "PRISM_WEB_STATIC": "",
            "PRISM_WEB_COOKIE_SECURE": "",
            "PRISM_FETCH_ALLOW_PRIVATE": "", "PRISM_FETCH_USE_JINA_READER": "",
            "PRISM_FETCH_TIMEOUT_SECONDS": "", "PRISM_FETCH_MAX_DOWNLOAD_BYTES": "",
            "PRISM_FETCH_RETRY_ATTEMPTS": "", "PRISM_FETCH_RETRY_BACKOFF_BASE": "",
            "PRISM_FETCH_MAX_REDIRECTS": "",
        }
        env.update(extra)
        return env

    def test_store_overrides_apply_and_env_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict("os.environ", self._env(tmp)):
                s = load_settings(require_telegram=False)
                self.assertIsNone(s.llm_api_key)
                self.assertEqual(s.llm_base_url, DEFAULT_LLM_BASE_URL)

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

    def test_web_and_fetch_settings_parse_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = self._env(
                tmp,
                PRISM_WEB_HOST="0.0.0.0",
                PRISM_WEB_PORT="7777",
                PRISM_WEB_RELOAD="true",
                PRISM_WEB_STATIC=str(Path(tmp) / "dist"),
                PRISM_WEB_COOKIE_SECURE="yes",
                PRISM_FETCH_ALLOW_PRIVATE="1",
                PRISM_FETCH_USE_JINA_READER="0",
                PRISM_FETCH_TIMEOUT_SECONDS="12.5",
                PRISM_FETCH_MAX_DOWNLOAD_BYTES="1234",
                PRISM_FETCH_RETRY_ATTEMPTS="5",
                PRISM_FETCH_RETRY_BACKOFF_BASE="2.5",
                PRISM_FETCH_MAX_REDIRECTS="4",
            )
            with patch.dict("os.environ", env):
                web = load_web_settings()
                self.assertEqual(web.host, "0.0.0.0")
                self.assertEqual(web.port, 7777)
                self.assertTrue(web.reload)
                self.assertEqual(web.static_path, Path(tmp) / "dist")
                self.assertTrue(web.cookie_secure)

                fetch = load_fetch_settings()
                self.assertTrue(fetch.allow_private)
                self.assertFalse(fetch.use_jina_reader)
                self.assertEqual(fetch.timeout_seconds, 12.5)
                self.assertEqual(fetch.max_download_bytes, 1234)
                self.assertEqual(fetch.retry_attempts, 5)
                self.assertEqual(fetch.retry_backoff_base, 2.5)
                self.assertEqual(fetch.max_redirects, 4)

    def test_index_settings_use_runtime_overrides(self) -> None:
        if importlib.util.find_spec("httpx") is None:
            self.skipTest("httpx is not installed")
        from prism.index import load_index_settings_from_env

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict("os.environ", self._env(tmp)):
                settings_store.save_overrides(
                    {
                        "embedding_api_key": "sk-store",
                        "embedding_model": "embed-model",
                        "embedding_base_url": "https://emb.example/v1",
                    }
                )
                sqlite_path, _database, indexer = load_index_settings_from_env()

                self.assertEqual(sqlite_path, Path(tmp) / "prism.sqlite3")
                self.assertEqual(indexer.lancedb_path, Path(tmp) / "lancedb")
                self.assertEqual(indexer.embedding_config.api_key, "sk-store")
                self.assertEqual(indexer.embedding_config.model, "embed-model")
                self.assertEqual(indexer.embedding_config.base_url, "https://emb.example/v1")

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
