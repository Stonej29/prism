from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from prism.config import Settings, load_settings
from prism.db import PrismDatabase
from prism.embedding import EmbeddingConfig
from prism.index import NoteIndexer
from prism.llm import LLMConfig
from prism.notes import (
    NoteService,
    extract_first_url,
    related_notes_for_record,
    scores_for_record,
    structured_summary,
    tags_for_record,
)

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

        existing = self.database.find_by_source_url(source_url)
        if existing:
            await message.reply_text(_already_saved_reply(existing))
            return

        await message.reply_text("Saving...")
        asyncio.create_task(self._save_url_task(source_url, message))

    async def _save_url_task(self, source_url: str, message) -> None:
        try:
            result = await asyncio.to_thread(self.notes.save_url, source_url)
        except Exception as exc:
            LOGGER.exception("Background save_url failed for %s", source_url)
            await message.reply_text(f"Failed to save {source_url}: {type(exc).__name__}: {exc}")
            return
        record = result.record
        if result.created:
            await message.reply_text(self._saved_reply(record))
        else:
            await message.reply_text(_already_saved_reply(record))

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

        await message.reply_text(_more_reply(record))

    async def handle_related(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_allowed(update):
            return

        message = update.effective_message
        if not message:
            return

        args = list(context.args) if context.args else []
        limit = 5
        if args and args[-1].isdigit():
            limit = max(1, min(20, int(args.pop())))
        query = " ".join(args).strip()
        if not query:
            await message.reply_text("Usage: /related <query-or-note_id> [n]")
            return

        indexer = self.notes.indexer
        if not indexer or not indexer.is_configured:
            await message.reply_text("Semantic search is not configured. Set EMBEDDING_API_KEY and EMBEDDING_MODEL.")
            return

        try:
            record = self.database.find_by_note_id(query.lower()) if len(query.split()) == 1 else None
            if record:
                results = indexer.search_related(record, limit=limit)
            else:
                results = indexer.search_text(query, limit=limit)
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

        note_id = context.args[0].strip().lower()
        record = self.database.find_by_note_id(note_id)
        if not record:
            await message.reply_text(f"No note found for {note_id}.")
            return

        await message.reply_text(f"Reprocessing {note_id}...")
        asyncio.create_task(self._reprocess_task(note_id, message))

    async def _reprocess_task(self, note_id: str, message) -> None:
        try:
            result = await asyncio.to_thread(self.notes.reprocess, note_id)
        except Exception as exc:
            LOGGER.exception("Background reprocess failed for %s", note_id)
            await message.reply_text(f"Reprocess failed: {type(exc).__name__}: {exc}")
            return
        if not result.record:
            await message.reply_text(result.message)
            return
        if result.ok:
            await message.reply_text(self._saved_reply(result.record).replace("Saved:", "Reprocessed:", 1))
            return
        await message.reply_text(result.message)

    async def handle_recent(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_allowed(update):
            return
        message = update.effective_message
        if not message:
            return
        n = 5
        if context.args:
            try:
                n = max(1, min(10, int(context.args[0])))
            except ValueError:
                await message.reply_text("Usage: /recent [n]  (n is a number, max 10)")
                return
        records = self.database.list_recent_notes(n)
        if not records:
            await message.reply_text("No notes saved yet.")
            return
        await message.reply_text(_recent_reply(records))

    async def handle_tags(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_allowed(update):
            return
        message = update.effective_message
        if not message:
            return
        if not context.args:
            tag_counts = self.database.list_tags_with_counts()
            if not tag_counts:
                await message.reply_text("No tags yet. Save some URLs and wait for LLM processing.")
                return
            await message.reply_text(_tags_list_reply(tag_counts))
            return
        tag = context.args[0].strip().lstrip("#").lower()
        records = self.database.list_notes_by_tag(tag, limit=10)
        if not records:
            await message.reply_text(f"No notes tagged #{tag}.")
            return
        await message.reply_text(_tags_notes_reply(tag, records))

    async def handle_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_allowed(update):
            return
        message = update.effective_message
        if not message:
            return
        stats = self.database.get_note_stats()
        await message.reply_text(_status_reply(stats, self.notes.indexer))

    async def handle_find(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_allowed(update):
            return
        message = update.effective_message
        if not message:
            return
        query = " ".join(context.args).strip() if context.args else ""
        if not query:
            await message.reply_text("Usage: /find <query>")
            return
        indexer = self.notes.indexer
        if not indexer or not indexer.is_configured:
            await message.reply_text("Semantic search is not configured. Set EMBEDDING_API_KEY and EMBEDDING_MODEL.")
            return
        await message.reply_text(f'Searching for "{_shorten(query, 60)}"...')
        asyncio.create_task(self._find_task(query, message))

    async def _find_task(self, query: str, message) -> None:
        try:
            results = await asyncio.to_thread(self.notes.indexer.search_text, query, limit=5)
        except Exception as exc:
            await message.reply_text(f"Search failed: {type(exc).__name__}: {exc}")
            return
        if not results:
            if self.notes.indexer.index_is_empty():
                await message.reply_text("The semantic index is empty. Run: PYTHONPATH=src python -m prism.index rebuild")
            else:
                await message.reply_text("No results found.")
            return
        await message.reply_text(_related_reply(results))

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


def _already_saved_reply(record) -> str:
    s = structured_summary(record)
    generated = record.llm_status == "generated"
    quick = s.get("quick_summary") if generated else None
    summary = quick.strip() if isinstance(quick, str) and quick.strip() else record.summary
    tags = tags_for_record(record)
    tags_line = "Tags: " + " ".join(f"#{t}" for t in tags) if tags else ""
    parts = [f"Already saved: {record.title}", summary]
    if tags_line:
        parts.append(tags_line)
    parts.append(f"/more {record.note_id}")
    return "\n\n".join(parts)


def _more_reply(record) -> str:
    s = structured_summary(record)
    generated = record.llm_status == "generated"
    parts: list[str] = [record.title]

    quick = s.get("quick_summary") if generated else None
    if isinstance(quick, str) and quick.strip():
        parts.append(quick.strip())
    elif record.summary:
        parts.append(record.summary)

    if generated:
        detailed = s.get("detailed_summary")
        if isinstance(detailed, str) and detailed.strip():
            parts.append(_shorten(detailed.strip(), 500))

        claims = s.get("key_claims")
        if isinstance(claims, list):
            lines = [f"- {str(c).strip()}" for c in claims[:5] if str(c).strip()]
            if lines:
                parts.append("Key claims:\n" + "\n".join(lines))

        limitations = s.get("limitations")
        if isinstance(limitations, list):
            lines = [f"- {str(l).strip()}" for l in limitations[:3] if str(l).strip()]
            if lines:
                parts.append("Limitations:\n" + "\n".join(lines))

    scores = scores_for_record(record)
    if scores:
        score_parts = [
            f"{key} {int(scores[key])}"
            for key in ("relevance", "novelty", "overall")
            if key in scores
        ]
        if score_parts:
            parts.append("Scores: " + " · ".join(score_parts))

    related = related_notes_for_record(record)
    if related:
        rel_lines = [f"- {item['title']} (/more {item['id']})" for item in related[:5]]
        parts.append("Related:\n" + "\n".join(rel_lines))

    parts.append(f"Source: {record.source_url}")

    reply = "\n\n".join(parts)
    if len(reply) > 4000:
        reply = reply[:4000].rstrip() + "..."
    return reply


def _status_reply(stats, indexer) -> str:
    lines = [
        f"Notes: {stats.total}",
        f"LLM: {stats.llm_generated} generated, {stats.llm_failed} failed, {stats.llm_skipped} skipped",
        f"Embeddings: {stats.embedding_indexed} indexed, {stats.embedding_failed} failed, {stats.embedding_skipped} skipped",
    ]
    if indexer and indexer.is_configured:
        index_state = "empty" if indexer.index_is_empty() else "ready"
        lines.append(f"Index: {index_state}")
    else:
        lines.append("Index: not configured (set EMBEDDING_API_KEY and EMBEDDING_MODEL)")
    return "\n".join(lines)


def _recent_reply(records) -> str:
    lines = ["Recent notes:"]
    for r in records:
        date = r.date_saved[:10]
        lines.append(f"{r.title}\n{r.source_kind}, {date}\n/more {r.note_id}")
    return "\n\n".join(lines)


def _tags_list_reply(tag_counts) -> str:
    lines = ["Tags:"]
    for tag, count in tag_counts:
        lines.append(f"#{tag} ({count})")
    return "\n".join(lines)


def _tags_notes_reply(tag: str, records) -> str:
    lines = [f"Notes tagged #{tag}:"]
    for r in records:
        lines.append(f"{r.title}\n{r.source_kind}, {r.date_saved[:10]}\n/more {r.note_id}")
    return "\n\n".join(lines)


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
    application.add_handler(CommandHandler("status", bot.handle_status))
    application.add_handler(CommandHandler("recent", bot.handle_recent))
    application.add_handler(CommandHandler("tags", bot.handle_tags))
    application.add_handler(CommandHandler("find", bot.handle_find))
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
