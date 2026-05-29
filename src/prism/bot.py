from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from prism.config import Settings, load_settings
from prism.db import PrismDatabase
from prism.embedding import EmbeddingConfig
from prism.index import NoteIndexer
from prism.llm import LLMConfig
from prism.notes import NoteService, extract_first_url, more_summary_for_record, tags_for_record

LOGGER = logging.getLogger(__name__)


class PrismBot:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.database = PrismDatabase(settings.sqlite_path)
        self.notes = NoteService(
            settings.vault_path,
            self.database,
            settings.archive_path,
            LLMConfig(settings.llm_base_url, settings.llm_api_key, settings.llm_model),
            NoteIndexer(
                settings.lancedb_path,
                EmbeddingConfig(settings.embedding_base_url, settings.embedding_api_key, settings.embedding_model),
            ),
        )

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        if not await self._is_allowed(update):
            return

        message = update.effective_message
        if not message or not message.text:
            return

        source_url = extract_first_url(message.text)
        if not source_url:
            await message.reply_text("Send a message containing a URL to save it.")
            return

        result = self.notes.save_url(source_url)
        record = result.record
        if result.created:
            reply = self._saved_reply(record)
        else:
            prefix = "Already saved" if result.duplicate_reason == "source_url" else "Already captured"
            archive_status = "archived" if record.fetch_status == "fetched" else "fetch failed"
            reply = f"{prefix}: {record.title}\n{record.source_kind}, {archive_status}\n/more {record.note_id}"
        await message.reply_text(reply)

    async def handle_more(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_allowed(update):
            return

        message = update.effective_message
        if not message:
            return

        if not context.args:
            await message.reply_text("Usage: /more <id>")
            return

        note_id = context.args[0].strip().lower()
        record = self.database.find_by_note_id(note_id)
        if not record:
            await message.reply_text(f"No note found for {note_id}.")
            return

        await message.reply_text(
            f"{record.title}\n"
            f"{more_summary_for_record(record)}\n"
            f"Status: {record.status}\n"
            f"Fetch: {record.fetch_status}\n"
            f"LLM: {record.llm_status}\n"
            f"Kind: {record.source_kind}\n"
            f"Path: {record.note_path}\n"
            f"Source: {record.source_url}"
        )

    async def handle_related(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_allowed(update):
            return

        message = update.effective_message
        if not message:
            return

        query = " ".join(context.args).strip()
        if not query:
            await message.reply_text("Usage: /related <query-or-note_id>")
            return

        indexer = self.notes.indexer
        if not indexer or not indexer.is_configured:
            await message.reply_text("Semantic search is not configured. Set EMBEDDING_API_KEY and EMBEDDING_MODEL.")
            return

        try:
            record = self.database.find_by_note_id(query.lower()) if len(query.split()) == 1 else None
            if record:
                results = indexer.search_related(record, limit=5)
            else:
                results = indexer.search_text(query, limit=5)
        except Exception as exc:
            await message.reply_text(f"Related search failed: {type(exc).__name__}: {exc}")
            return

        if not results:
            if indexer.index_is_empty():
                await message.reply_text("The semantic index is empty. Run: PYTHONPATH=src python -m prism.index rebuild")
            else:
                await message.reply_text("No related notes found.")
            return

        await message.reply_text(_related_reply(results))

    async def handle_reprocess(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_allowed(update):
            return

        message = update.effective_message
        if not message:
            return

        if not context.args:
            await message.reply_text("Usage: /reprocess <id>")
            return

        result = self.notes.reprocess(context.args[0])
        if not result.record:
            await message.reply_text(result.message)
            return
        if result.ok:
            await message.reply_text(self._saved_reply(result.record).replace("Saved:", "Reprocessed:", 1))
            return
        await message.reply_text(result.message)

    def _saved_reply(self, record) -> str:
        if record.llm_status == "generated":
            tags = " ".join(f"#{tag}" for tag in tags_for_record(record))
            tags_line = f"\nTags: {tags}" if tags else ""
            return f"Saved: {record.title}\n{record.summary}{tags_line}\n/more {record.note_id}"
        archive_status = "archived" if record.fetch_status == "fetched" else "fetch failed"
        llm_status = "LLM failed" if record.llm_status == "failed" else "LLM skipped"
        return f"Saved: {record.title}\n{record.source_kind}, {archive_status}, {llm_status}\n/more {record.note_id}"

    async def handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        if not await self._is_allowed(update):
            return
        if update.effective_message:
            await update.effective_message.reply_text("Send a URL to save and archive it in PRISM.")

    async def _is_allowed(self, update: Update) -> bool:
        user = update.effective_user
        if user and user.id in self.settings.telegram_allowed_user_ids:
            return True
        LOGGER.warning("Rejected unauthorized Telegram user: %s", user.id if user else "unknown")
        if update.effective_message:
            await update.effective_message.reply_text("Unauthorized.")
        return False


def _related_reply(results) -> str:
    lines = ["Related notes:"]
    for item in results:
        summary = _shorten(item.summary, 180)
        lines.append(f"{item.title} ({item.score:.3f})\n{summary}\n/more {item.note_id}")
    return "\n\n".join(lines)


def _shorten(text: str, limit: int) -> str:
    clean = " ".join(text.split())
    if len(clean) <= limit:
        return clean
    return clean[:limit].rstrip() + "..."


def build_application(settings: Settings) -> Application:
    bot = PrismBot(settings)
    application = Application.builder().token(settings.telegram_bot_token).build()
    application.add_handler(CommandHandler("start", bot.handle_start))
    application.add_handler(CommandHandler("more", bot.handle_more))
    application.add_handler(CommandHandler("reprocess", bot.handle_reprocess))
    application.add_handler(CommandHandler("related", bot.handle_related))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_message))
    return application


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    settings = load_settings()
    settings.vault_path.mkdir(parents=True, exist_ok=True)
    settings.archive_path.mkdir(parents=True, exist_ok=True)
    LOGGER.info("Starting PRISM bot with vault at %s, archives at %s, and SQLite at %s", settings.vault_path, settings.archive_path, settings.sqlite_path)
    build_application(settings).run_polling(allowed_updates=Update.ALL_TYPES)
