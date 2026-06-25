from __future__ import annotations

import asyncio
import html
import logging
import secrets
import time

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from prism.config import Settings, load_settings
from prism.db import PrismDatabase
from prism.embedding import EmbeddingConfig
from prism.ideas import IdeaService
from prism.index import NoteIndexer
from prism.llm import LLMConfig
from prism.notes import (
    NOTE_STATUSES,
    PURPOSE_VALUES,
    NoteService,
    _json_array,
    extract_first_url,
    related_notes_for_record,
    scores_for_record,
    structured_summary,
    tags_for_record,
)
from prism.proposals import ProposalService, describe_proposal
from prism.services import Services
from prism.worker.config import load_worker_config
from prism.worker.ingest import run_feed_ingestion
from prism.worker.traversal import run_graph_traversal

LOGGER = logging.getLogger(__name__)
HTML_PARSE_MODE = "HTML"

PAGE_SIZE = 5
MAX_SEMANTIC_RESULTS = 20

# Commands registered with Telegram's command menu, and the source for /help.
COMMANDS = [
    ("help", "Show all commands"),
    ("ask", "Answer a question from your saved notes"),
    ("find", "Semantic search of your notes"),
    ("related", "Find notes related to a query or note id"),
    ("recent", "Browse recent notes"),
    ("inbox", "Browse unreviewed notes (review queue)"),
    ("tags", "Browse tags, or notes for a tag"),
    ("more", "Show the full detail of a note"),
    ("idea", "Generate a project idea, then rate it"),
    ("ideas", "Browse generated ideas with ratings"),
    ("proposals", "Review graph maintenance proposals"),
    ("ingest", "Pull configured feeds now"),
    ("traverse", "Run graph maintenance now"),
    ("rename", "Rename a note"),
    ("status_set", "Set a note's review status"),
    ("purpose", "Set a note's purpose (Thesis/Work/Self-Host/Dataset/Keep/none)"),
    ("reprocess", "Re-run LLM generation for a note"),
    ("reprocess_all", "Re-run LLM generation for every note"),
    ("repersonalize", "Re-run only personalization for a note"),
    ("retry_failed", "Retry failed LLM and embedding work"),
    ("delete", "Delete a note or idea after confirmation"),
    ("wipe_all", "Wipe all saved notes, ideas, archives, and index cache"),
    ("reset_me", "Replace the personal profile from text"),
    ("update_me", "Merge new text into the personal profile"),
    ("status", "Show note, LLM, and index counts"),
]


class PrismBot:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.database = PrismDatabase(settings.sqlite_path)
        llm_config = LLMConfig(settings.llm_base_url, settings.llm_api_key, settings.llm_model)
        indexer = NoteIndexer(
            settings.lancedb_path,
            EmbeddingConfig(settings.embedding_base_url, settings.embedding_api_key, settings.embedding_model),
        )
        self.notes = NoteService(
            settings.vault_path,
            self.database,
            settings.archive_path,
            llm_config,
            indexer,
        )
        self.ideas = IdeaService(settings.vault_path, self.database, llm_config, indexer)
        self.proposals = ProposalService(self.database, self.notes)
        self._semantic_pages: dict[str, tuple[str, list]] = {}
        self._wipe_codes: dict[int, str] = {}
        # token -> URL, for the "Save anyway" duplicate override (callback_data is too
        # small to carry a full URL).
        self._save_anyway_urls: dict[str, str] = {}

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
            await message.reply_text(
                _already_saved_reply(existing, "source_url"),
                parse_mode=HTML_PARSE_MODE,
                reply_markup=self._save_anyway_keyboard(source_url),
            )
            return

        await message.reply_text("Saving...")
        asyncio.create_task(self._save_url_task(source_url, message))

    async def _save_url_task(self, source_url: str, message, force: bool = False) -> None:
        try:
            result = await asyncio.to_thread(self.notes.save_url, source_url, "telegram", force=force)
        except Exception as exc:
            LOGGER.exception("Background save_url failed for %s", source_url)
            await message.reply_text(f"Failed to save {source_url}: {type(exc).__name__}: {exc}")
            return
        record = result.record
        if result.created:
            text = self._saved_reply(record)
            if result.similar_note_id:
                text += "\n\n<i>Looks similar to</i> " + _cmd("more", result.similar_note_id)
            await message.reply_text(text, parse_mode=HTML_PARSE_MODE)
        else:
            await message.reply_text(
                _already_saved_reply(record, result.duplicate_reason),
                parse_mode=HTML_PARSE_MODE,
                reply_markup=self._save_anyway_keyboard(source_url),
            )

    async def handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        if not await self._is_allowed(update):
            return
        message = update.effective_message
        if not message or not message.document:
            return
        doc = message.document
        filename = doc.file_name or "upload.pdf"
        mime = doc.mime_type or ""
        is_pdf = mime.lower().startswith("application/pdf") or filename.lower().endswith(".pdf")
        if not is_pdf:
            await message.reply_text("Only PDF documents are supported right now.")
            return
        await message.reply_text(f"Saving {filename}...")
        asyncio.create_task(self._save_upload_task(doc.file_id, filename, mime, message))

    async def _save_upload_task(self, file_id: str, filename: str, mime: str, message) -> None:
        try:
            tg_file = await message.get_bot().get_file(file_id)
            data = bytes(await tg_file.download_as_bytearray())
            result = await asyncio.to_thread(self.notes.save_upload, filename, data, mime, "telegram")
        except Exception as exc:
            LOGGER.exception("Background save_upload failed for %s", filename)
            await message.reply_text(f"Failed to save {filename}: {type(exc).__name__}: {exc}")
            return
        record = result.record
        if result.created:
            await message.reply_text(self._saved_reply(record), parse_mode=HTML_PARSE_MODE)
        else:
            await message.reply_text(_already_saved_reply(record), parse_mode=HTML_PARSE_MODE)

    async def handle_more(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_allowed(update):
            return

        message = update.effective_message
        if not message:
            return

        if not context.args:
            records = self.database.list_recent_notes(1)
            if not records:
                await message.reply_text("No notes saved yet.")
                return
            await message.reply_text(_more_reply(records[0]), parse_mode=HTML_PARSE_MODE)
            return

        note_id = context.args[0].strip().lower()
        record = self.database.find_by_note_id(note_id)
        if not record:
            await message.reply_text(f"No note found for {note_id}.")
            return

        await message.reply_text(_more_reply(record), parse_mode=HTML_PARSE_MODE)

    async def handle_related(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_allowed(update):
            return

        message = update.effective_message
        if not message:
            return

        args = list(context.args) if context.args else []
        max_results = MAX_SEMANTIC_RESULTS
        if args and args[-1].isdigit():
            max_results = max(1, min(MAX_SEMANTIC_RESULTS, int(args.pop())))
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
                results = indexer.search_related(record, limit=max_results)
            else:
                results = indexer.search_text(query, limit=max_results)
        except Exception as exc:
            await message.reply_text(f"Related search failed: {type(exc).__name__}: {exc}")
            return

        if not results:
            if indexer.index_is_empty():
                await message.reply_text("The semantic index is empty. Run: PYTHONPATH=src python -m prism.index rebuild")
            else:
                await message.reply_text("No related notes found.")
            return

        title = f'Related to "{_shorten(query, 50)}":'
        token = self._store_semantic_page(title, results)
        text, keyboard = _semantic_page_view(token, title, results, 0)
        if keyboard:
            await message.reply_text(text, reply_markup=keyboard, parse_mode=HTML_PARSE_MODE)
        else:
            await message.reply_text(text, parse_mode=HTML_PARSE_MODE)

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
            await message.reply_text(self._saved_reply(result.record).replace("<b>Saved:</b>", "<b>Reprocessed:</b>", 1), parse_mode=HTML_PARSE_MODE)
            return
        await message.reply_text(result.message)

    async def handle_reprocess_all(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        if not await self._is_allowed(update):
            return

        message = update.effective_message
        if not message:
            return

        await message.reply_text("Reprocessing all notes — this may take a while...")
        asyncio.create_task(self._reprocess_all_task(message))

    async def _reprocess_all_task(self, message) -> None:
        try:
            summary = await asyncio.to_thread(self.notes.reprocess_all)
        except Exception as exc:
            LOGGER.exception("Background reprocess_all failed")
            await message.reply_text(f"Reprocess all failed: {type(exc).__name__}: {exc}")
            return
        text = f"Reprocessed {summary.reprocessed}/{summary.total} notes."
        if summary.failed:
            text += f" {summary.failed} failed."
        await message.reply_text(text)

    async def handle_repersonalize(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_allowed(update):
            return

        message = update.effective_message
        if not message:
            return

        if not context.args:
            await message.reply_text("Usage: /repersonalize <id>")
            return

        note_id = context.args[0].strip().lower()
        record = self.database.find_by_note_id(note_id)
        if not record:
            await message.reply_text(f"No note found for {note_id}.")
            return

        await message.reply_text(f"Re-personalizing {note_id}...")
        asyncio.create_task(self._repersonalize_task(note_id, message))

    async def _repersonalize_task(self, note_id: str, message) -> None:
        try:
            result = await asyncio.to_thread(self.notes.repersonalize, note_id)
        except Exception as exc:
            LOGGER.exception("Background repersonalize failed for %s", note_id)
            await message.reply_text(f"Re-personalize failed: {type(exc).__name__}: {exc}")
            return
        if not result.record:
            await message.reply_text(result.message)
            return
        if result.ok:
            await message.reply_text(self._saved_reply(result.record).replace("<b>Saved:</b>", "<b>Re-personalized:</b>", 1), parse_mode=HTML_PARSE_MODE)
            return
        await message.reply_text(result.message)

    async def handle_rename(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_allowed(update):
            return
        message = update.effective_message
        if not message:
            return
        if len(context.args) < 2:
            await message.reply_text("Usage: /rename <id> <new title>")
            return
        note_id = context.args[0].strip().lower()
        title = " ".join(context.args[1:]).strip()
        record = self.database.find_by_note_id(note_id)
        if not record:
            await message.reply_text(f"No note found for {note_id}.")
            return
        try:
            updated = await asyncio.to_thread(self.notes.rename_note, record, title)
        except ValueError as exc:
            await message.reply_text(str(exc))
            return
        except Exception as exc:
            LOGGER.exception("Rename failed for %s", note_id)
            await message.reply_text(f"Rename failed: {type(exc).__name__}: {exc}")
            return
        await message.reply_text(f"Renamed {updated.note_id} → <b>{_h(updated.title)}</b>", parse_mode=HTML_PARSE_MODE)

    async def handle_status_set(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_allowed(update):
            return
        message = update.effective_message
        if not message:
            return
        if len(context.args) < 2:
            await message.reply_text(f"Usage: /status_set <id> <{'/'.join(NOTE_STATUSES)}>")
            return
        note_id = context.args[0].strip().lower()
        status = context.args[1].strip().lower()
        record = self.database.find_by_note_id(note_id)
        if not record:
            await message.reply_text(f"No note found for {note_id}.")
            return
        try:
            updated = await asyncio.to_thread(self.notes.set_status, record, status)
        except ValueError as exc:
            await message.reply_text(str(exc))
            return
        except Exception as exc:
            LOGGER.exception("Set status failed for %s", note_id)
            await message.reply_text(f"Set status failed: {type(exc).__name__}: {exc}")
            return
        await message.reply_text(f"Set {updated.note_id} status to <b>{_h(updated.status)}</b>", parse_mode=HTML_PARSE_MODE)

    async def handle_purpose(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_allowed(update):
            return
        message = update.effective_message
        if not message:
            return
        if len(context.args) < 2:
            await message.reply_text(f"Usage: /purpose <id> <{'/'.join(PURPOSE_VALUES)}/none>")
            return
        note_id = context.args[0].strip().lower()
        purpose = " ".join(context.args[1:]).strip()
        record = self.database.find_by_note_id(note_id)
        if not record:
            await message.reply_text(f"No note found for {note_id}.")
            return
        try:
            updated = await asyncio.to_thread(self.notes.set_purpose, record, purpose)
        except ValueError as exc:
            await message.reply_text(str(exc))
            return
        except Exception as exc:
            LOGGER.exception("Set purpose failed for %s", note_id)
            await message.reply_text(f"Set purpose failed: {type(exc).__name__}: {exc}")
            return
        label = updated.purpose or "Unsorted"
        await message.reply_text(f"Set {updated.note_id} purpose to <b>{_h(label)}</b>", parse_mode=HTML_PARSE_MODE)

    async def handle_retry_failed(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_allowed(update):
            return
        message = update.effective_message
        if not message:
            return
        limit = 25
        if context.args and context.args[0].isdigit():
            limit = max(1, min(100, int(context.args[0])))
        await message.reply_text(f"Retrying up to {limit} failed notes...")
        asyncio.create_task(self._retry_failed_task(limit, message))

    async def _retry_failed_task(self, limit: int, message) -> None:
        try:
            result = await asyncio.to_thread(self.notes.retry_failed, limit)
        except Exception as exc:
            LOGGER.exception("Background retry_failed failed")
            await message.reply_text(f"Retry failed: {type(exc).__name__}: {exc}")
            return
        await message.reply_text(_retry_failed_reply(result), parse_mode=HTML_PARSE_MODE)

    async def handle_delete(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_allowed(update):
            return
        message = update.effective_message
        if not message:
            return
        if not context.args:
            await message.reply_text("Usage: /delete <note-or-idea-id>")
            return
        item_id = context.args[0].strip().lower()
        record = self.database.find_by_note_id(item_id)
        if record:
            await message.reply_text(
                f"Delete note <b>{_h(record.title)}</b> ({_cmd('more', record.note_id)})?",
                reply_markup=_delete_keyboard("note", record.note_id),
                parse_mode=HTML_PARSE_MODE,
            )
            return
        idea = self.database.find_by_idea_id(item_id)
        if idea:
            await message.reply_text(
                f"Delete idea <b>{_h(idea.title)}</b> ({_h(idea.idea_id)})?",
                reply_markup=_delete_keyboard("idea", idea.idea_id),
                parse_mode=HTML_PARSE_MODE,
            )
            return
        await message.reply_text(f"No note or idea found for {item_id}.")

    async def handle_delete_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        query = update.callback_query
        if not query:
            return
        await query.answer()
        user = update.effective_user
        if not user or user.id not in self.settings.telegram_allowed_user_ids:
            return
        item_type, item_id, confirmed = _parse_delete_callback(query.data)
        if not item_type or not item_id:
            return
        if not confirmed:
            await query.edit_message_text("Delete cancelled.")
            return
        if item_type == "note":
            result = await asyncio.to_thread(self.notes.delete_note, item_id)
            await query.edit_message_text(_h(result.message), parse_mode=HTML_PARSE_MODE)
            return
        if item_type == "idea":
            record = await asyncio.to_thread(self.ideas.delete_idea, item_id)
            if record:
                await query.edit_message_text(f"Deleted idea {_h(record.idea_id)}: {_h(record.title)}", parse_mode=HTML_PARSE_MODE)
            else:
                await query.edit_message_text(f"No idea found for {_h(item_id)}.", parse_mode=HTML_PARSE_MODE)

    async def handle_wipe_all(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_allowed(update):
            return
        message = update.effective_message
        user = update.effective_user
        if not message or not user:
            return
        if not context.args:
            code = secrets.token_hex(3).upper()
            if not hasattr(self, "_wipe_codes"):
                self._wipe_codes = {}
            self._wipe_codes[user.id] = code
            await message.reply_text(
                "This will delete all saved notes, generated ideas, archives, and the semantic index cache. "
                f"To confirm, send <code>/wipe_all {code}</code>.",
                parse_mode=HTML_PARSE_MODE,
            )
            return
        code = context.args[0].strip().upper()
        if not hasattr(self, "_wipe_codes"):
            self._wipe_codes = {}
        expected = self._wipe_codes.get(user.id)
        if not expected or code != expected:
            await message.reply_text("Confirmation code did not match. Run /wipe_all to generate a new code.")
            return
        self._wipe_codes.pop(user.id, None)
        result = await asyncio.to_thread(self.notes.wipe_all)
        await message.reply_text(f"Wiped {result.notes} notes and {result.ideas} ideas.")

    async def handle_reset_me(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_allowed(update):
            return
        message = update.effective_message
        if not message:
            return
        user_text = " ".join(context.args).strip() if context.args else ""
        if not user_text:
            await message.reply_text("Usage: /reset_me <profile facts/preferences>")
            return
        await message.reply_text("Resetting personal profile...")
        asyncio.create_task(self._profile_task("reset", user_text, message))

    async def handle_update_me(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_allowed(update):
            return
        message = update.effective_message
        if not message:
            return
        user_text = " ".join(context.args).strip() if context.args else ""
        if not user_text:
            await message.reply_text("Usage: /update_me <new profile facts/preferences>")
            return
        await message.reply_text("Updating personal profile...")
        asyncio.create_task(self._profile_task("update", user_text, message))

    async def _profile_task(self, mode: str, user_text: str, message) -> None:
        try:
            if mode == "reset":
                result = await asyncio.to_thread(self.notes.reset_profile, user_text)
            else:
                result = await asyncio.to_thread(self.notes.update_profile, user_text)
        except Exception as exc:
            LOGGER.exception("Background profile %s failed", mode)
            await message.reply_text(f"Profile {mode} failed: {type(exc).__name__}: {exc}")
            return
        if not result.ok:
            await message.reply_text(result.message)
            return
        preview = _shorten(result.profile or "", 700)
        await message.reply_text(f"<b>{_h(result.message)}</b>\n\n{_h(preview)}", parse_mode=HTML_PARSE_MODE)

    async def handle_recent(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        if not await self._is_allowed(update):
            return
        message = update.effective_message
        if not message:
            return
        text, keyboard = self._page_view("recent", 0)
        await message.reply_text(text or "No notes saved yet.", reply_markup=keyboard, parse_mode=HTML_PARSE_MODE)

    async def handle_inbox(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        if not await self._is_allowed(update):
            return
        message = update.effective_message
        if not message:
            return
        text, keyboard = self._page_view("inbox", 0)
        await message.reply_text(text or "Inbox zero — no unreviewed notes.", reply_markup=keyboard, parse_mode=HTML_PARSE_MODE)

    async def handle_tags(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_allowed(update):
            return
        message = update.effective_message
        if not message:
            return
        if not context.args:
            text, keyboard = self._page_view("tags", 0)
            await message.reply_text(text or "No tags yet. Save some URLs and wait for LLM processing.", reply_markup=keyboard, parse_mode=HTML_PARSE_MODE)
            return
        tag = context.args[0].strip().lstrip("#").lower()
        text, keyboard = self._page_view("tagnotes", 0, tag=tag)
        await message.reply_text(text or f"No notes tagged #{_h(tag)}.", reply_markup=keyboard, parse_mode=HTML_PARSE_MODE)

    async def handle_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_allowed(update):
            return
        message = update.effective_message
        if not message:
            return
        stats = self.database.get_note_stats()
        await message.reply_text(_status_reply(stats, self.notes.indexer), parse_mode=HTML_PARSE_MODE)

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
        await message.reply_text(f'Searching for "{_shorten(query, 60)}"...')
        asyncio.create_task(self._find_task(query, message))

    async def _find_task(self, query: str, message) -> None:
        # Hybrid search (semantic + keyword); degrades to keyword-only when
        # embeddings are unconfigured, so /find always works.
        try:
            results = await asyncio.to_thread(self.notes.search, query, limit=MAX_SEMANTIC_RESULTS)
        except Exception as exc:
            await message.reply_text(f"Search failed: {type(exc).__name__}: {exc}")
            return
        if not results:
            indexer = self.notes.indexer
            if indexer and indexer.is_configured and indexer.index_is_empty():
                await message.reply_text("The semantic index is empty. Run: PYTHONPATH=src python -m prism.index rebuild")
            else:
                await message.reply_text("No results found.")
            return
        title = f'Search results for "{_shorten(query, 50)}":'
        token = self._store_semantic_page(title, results)
        text, keyboard = _semantic_page_view(token, title, results, 0)
        if keyboard:
            await message.reply_text(text, reply_markup=keyboard, parse_mode=HTML_PARSE_MODE)
        else:
            await message.reply_text(text, parse_mode=HTML_PARSE_MODE)

    async def handle_ask(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_allowed(update):
            return
        message = update.effective_message
        if not message:
            return
        question = " ".join(context.args).strip() if context.args else ""
        if not question:
            await message.reply_text("Usage: /ask <question>")
            return
        indexer = self.notes.indexer
        if not indexer or not indexer.is_configured:
            await message.reply_text("Semantic search is not configured. Set EMBEDDING_API_KEY and EMBEDDING_MODEL.")
            return
        if not self.notes.llm_config.is_configured:
            await message.reply_text("/ask needs LLM_API_KEY and LLM_MODEL.")
            return
        await message.reply_text(f'Searching your notes for "{_shorten(question, 60)}"...')
        asyncio.create_task(self._ask_task(question, message))

    async def _ask_task(self, question: str, message) -> None:
        try:
            result = await asyncio.to_thread(self.notes.ask, question, limit=MAX_SEMANTIC_RESULTS)
        except Exception as exc:
            LOGGER.exception("Background ask failed for %s", question)
            await message.reply_text(f"Ask failed: {type(exc).__name__}: {exc}")
            return
        if not result.ok:
            await message.reply_text(result.message)
            return
        token = self._store_semantic_page("Sources:", result.sources) if result.sources else None
        reply, keyboard = _ask_reply(result, token=token, offset=0)
        if keyboard:
            await message.reply_text(reply, reply_markup=keyboard, parse_mode=HTML_PARSE_MODE)
        else:
            await message.reply_text(reply, parse_mode=HTML_PARSE_MODE)

    async def handle_idea(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_allowed(update):
            return
        message = update.effective_message
        if not message:
            return
        if not self.ideas.llm_config.is_configured:
            await message.reply_text("Idea generation needs LLM_API_KEY and LLM_MODEL.")
            return
        topic = " ".join(context.args).strip() if context.args else ""
        ack = f'Generating idea about "{_shorten(topic, 60)}"...' if topic else "Generating idea..."
        await message.reply_text(ack)
        asyncio.create_task(self._idea_task(topic or None, message))

    async def _idea_task(self, topic, message) -> None:
        try:
            result = await asyncio.to_thread(self.ideas.generate_idea, topic)
        except Exception as exc:
            LOGGER.exception("Background generate_idea failed for topic %s", topic)
            await message.reply_text(f"Idea generation failed: {type(exc).__name__}: {exc}")
            return
        if not result.ok or not result.record:
            await message.reply_text(result.message)
            return
        await message.reply_text(_idea_reply(result.record), reply_markup=_rating_keyboard(result.record.idea_id), parse_mode=HTML_PARSE_MODE)

    async def handle_rating(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        query = update.callback_query
        if not query:
            return
        await query.answer()
        user = update.effective_user
        if not user or user.id not in self.settings.telegram_allowed_user_ids:
            return
        idea_id, rating = _parse_rating_callback(query.data)
        if not idea_id or rating is None:
            return
        try:
            record = await asyncio.to_thread(self.ideas.record_rating, idea_id, rating)
        except Exception as exc:
            LOGGER.exception("Rating failed for idea %s", idea_id)
            await query.edit_message_text(f"Rating failed: {type(exc).__name__}: {exc}")
            return
        if not record:
            await query.edit_message_text("Idea not found.")
            return
        await query.edit_message_text(f"<b>Rated {_stars(rating)}:</b> {_h(record.title)}", parse_mode=HTML_PARSE_MODE)

    async def handle_ideas(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        if not await self._is_allowed(update):
            return
        message = update.effective_message
        if not message:
            return
        text, keyboard = self._page_view("ideas", 0)
        await message.reply_text(text or "No ideas yet. Use <code>/idea</code> to generate one.", reply_markup=keyboard, parse_mode=HTML_PARSE_MODE)

    async def handle_proposals(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        if not await self._is_allowed(update):
            return
        message = update.effective_message
        if not message:
            return
        pending = self.proposals.list_pending(limit=10)
        if not pending:
            await message.reply_text("No pending proposals. The worker creates them during graph maintenance.")
            return
        await message.reply_text(f"<b>{len(pending)} pending proposal(s):</b>", parse_mode=HTML_PARSE_MODE)
        for record in pending:
            await message.reply_text(
                f"<b>Proposal {_h(record.proposal_id)}</b> ({_h(record.kind)})\n{_h(describe_proposal(record))}",
                reply_markup=_proposal_keyboard(record.proposal_id),
                parse_mode=HTML_PARSE_MODE,
            )

    async def handle_proposal_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        query = update.callback_query
        if not query:
            return
        await query.answer()
        user = update.effective_user
        if not user or user.id not in self.settings.telegram_allowed_user_ids:
            return
        action, proposal_id = _parse_proposal_callback(query.data)
        if not action or not proposal_id:
            return
        try:
            if action == "approve":
                result = await asyncio.to_thread(self.proposals.approve, proposal_id)
            else:
                result = await asyncio.to_thread(self.proposals.reject, proposal_id)
        except Exception as exc:
            LOGGER.exception("Proposal %s failed for %s", action, proposal_id)
            await query.edit_message_text(f"Proposal {action} failed: {type(exc).__name__}: {exc}")
            return
        await query.edit_message_text(_h(result.message), parse_mode=HTML_PARSE_MODE)

    async def handle_ingest(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        if not await self._is_allowed(update):
            return
        message = update.effective_message
        if not message:
            return
        config = load_worker_config()
        if not config.feeds:
            await message.reply_text("No feeds configured. Add them to feeds.yaml (PRISM_FEEDS_PATH).")
            return
        await message.reply_text(f"Pulling {len(config.feeds)} feed(s)...")
        asyncio.create_task(self._ingest_task(config.feeds, message))

    async def _ingest_task(self, feeds, message) -> None:
        try:
            summary = await asyncio.to_thread(run_feed_ingestion, self.notes, feeds)
        except Exception as exc:
            LOGGER.exception("Manual feed ingestion failed")
            await message.reply_text(f"Feed ingestion failed: {type(exc).__name__}: {exc}")
            return
        await message.reply_text(_ingest_reply(summary), parse_mode=HTML_PARSE_MODE)

    async def handle_traverse(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        if not await self._is_allowed(update):
            return
        message = update.effective_message
        if not message:
            return
        await message.reply_text("Running graph maintenance...")
        asyncio.create_task(self._traverse_task(message))

    async def _traverse_task(self, message) -> None:
        try:
            summary = await asyncio.to_thread(run_graph_traversal, self._services(), load_worker_config().traversal)
        except Exception as exc:
            LOGGER.exception("Manual graph traversal failed")
            await message.reply_text(f"Graph maintenance failed: {type(exc).__name__}: {exc}")
            return
        await message.reply_text(_traverse_reply(summary, self.proposals.count_pending()), parse_mode=HTML_PARSE_MODE)

    def _services(self) -> Services:
        return Services(
            settings=self.settings,
            database=self.database,
            indexer=self.notes.indexer,
            notes=self.notes,
            ideas=self.ideas,
        )

    async def handle_page(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        query = update.callback_query
        if not query:
            return
        await query.answer()
        user = update.effective_user
        if not user or user.id not in self.settings.telegram_allowed_user_ids:
            return
        kind, offset, tag = _parse_page_callback(query.data)
        if not kind:
            return
        text, keyboard = self._page_view(kind, offset, tag=tag)
        if not text:
            return
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode=HTML_PARSE_MODE)

    async def handle_semantic_page(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        query = update.callback_query
        if not query:
            return
        await query.answer()
        user = update.effective_user
        if not user or user.id not in self.settings.telegram_allowed_user_ids:
            return
        token, offset = _parse_semantic_page_callback(query.data)
        if not token:
            return
        cached = self._semantic_cache().get(token)
        if not cached:
            await query.edit_message_text("Those search results expired. Run the command again.")
            return
        title, results = cached
        text, keyboard = _semantic_page_view(token, title, results, offset)
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode=HTML_PARSE_MODE)

    def _semantic_cache(self) -> dict[str, tuple[str, list]]:
        if not hasattr(self, "_semantic_pages"):
            self._semantic_pages = {}
        return self._semantic_pages

    def _save_anyway_cache(self) -> dict[str, str]:
        if not hasattr(self, "_save_anyway_urls"):
            self._save_anyway_urls: dict[str, str] = {}
        return self._save_anyway_urls

    def _save_anyway_keyboard(self, url: str) -> InlineKeyboardMarkup:
        cache = self._save_anyway_cache()
        token = secrets.token_urlsafe(6)[:8]
        cache[token] = url
        if len(cache) > 100:
            for old in list(cache)[:50]:
                cache.pop(old, None)
        return InlineKeyboardMarkup([[InlineKeyboardButton("Save anyway", callback_data=f"saveanyway:{token}")]])

    async def handle_save_anyway(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        query = update.callback_query
        if not query:
            return
        await query.answer()
        user = update.effective_user
        if not user or user.id not in self.settings.telegram_allowed_user_ids:
            return
        token = (query.data or "").split(":", 1)[-1]
        url = self._save_anyway_cache().pop(token, None)
        await query.edit_message_reply_markup(reply_markup=None)
        if not url:
            await query.message.reply_text("That save-anyway option expired. Send the URL again.")
            return
        await query.message.reply_text("Saving anyway...")
        asyncio.create_task(self._save_url_task(url, query.message, force=True))

    def _store_semantic_page(self, title: str, results: list) -> str:
        cache = self._semantic_cache()
        token = secrets.token_urlsafe(6)[:8]
        cache[token] = (title, results)
        if len(cache) > 100:
            for old_token in list(cache)[:50]:
                cache.pop(old_token, None)
        return token

    def _page_view(self, kind: str, offset: int, tag: str | None = None):
        offset = max(0, offset)
        if kind == "recent":
            rows = self.database.list_recent_notes(PAGE_SIZE + 1, offset)
            page, more = rows[:PAGE_SIZE], len(rows) > PAGE_SIZE
            text = _recent_reply(page) if page else None
        elif kind == "inbox":
            rows = self.database.list_inbox_notes(PAGE_SIZE + 1, offset)
            page, more = rows[:PAGE_SIZE], len(rows) > PAGE_SIZE
            text = _recent_reply(page) if page else None
        elif kind == "ideas":
            rows = self.database.list_recent_ideas(PAGE_SIZE + 1, offset)
            page, more = rows[:PAGE_SIZE], len(rows) > PAGE_SIZE
            text = _ideas_list_reply(page) if page else None
        elif kind == "tags":
            counts = self.database.list_tags_with_counts()
            page, more = counts[offset:offset + PAGE_SIZE], len(counts) > offset + PAGE_SIZE
            text = _tags_list_reply(page) if page else None
        elif kind == "tagnotes" and tag:
            rows = self.database.list_notes_by_tag(tag, PAGE_SIZE + 1, offset)
            page, more = rows[:PAGE_SIZE], len(rows) > PAGE_SIZE
            text = _tags_notes_reply(tag, page) if page else None
        else:
            return None, None
        return text, _page_keyboard(kind, offset, more, tag)

    def _saved_reply(self, record) -> str:
        if record.llm_status == "generated":
            tags = " ".join(f"#{_h(tag)}" for tag in tags_for_record(record))
            tags_line = f"\n<b>Tags:</b> {tags}" if tags else ""
            return f"<b>Saved:</b> {_h(record.title)}\n{_h(record.summary)}{tags_line}\n{_cmd('more', record.note_id)}"
        archive_status = "archived" if record.fetch_status == "fetched" else "fetch failed"
        llm_status = "LLM failed" if record.llm_status == "failed" else "LLM skipped"
        return f"<b>Saved:</b> {_h(record.title)}\n{_h(record.source_kind)}, {_h(archive_status)}, {_h(llm_status)}\n{_cmd('more', record.note_id)}"

    async def handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        if not await self._is_allowed(update):
            return
        if update.effective_message:
            await update.effective_message.reply_text(
                "Send a URL to save and archive it in PRISM.\n\n" + _HELP_TEXT,
                parse_mode=HTML_PARSE_MODE,
            )

    async def handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        if not await self._is_allowed(update):
            return
        if update.effective_message:
            await update.effective_message.reply_text(_HELP_TEXT, parse_mode=HTML_PARSE_MODE)

    async def _is_allowed(self, update: Update) -> bool:
        user = update.effective_user
        if user and user.id in self.settings.telegram_allowed_user_ids:
            return True
        LOGGER.warning("Rejected unauthorized Telegram user: %s", user.id if user else "unknown")
        if update.effective_message:
            await update.effective_message.reply_text("Unauthorized.")
        return False


_DUPLICATE_REASON_TEXT = {
    "source_url": "same URL",
    "resolved_url": "same final URL after redirects",
    "content_hash": "same content",
}


def _already_saved_reply(record, reason: str | None = None) -> str:
    s = structured_summary(record)
    generated = record.llm_status == "generated"
    quick = s.get("quick_summary") if generated else None
    summary = quick.strip() if isinstance(quick, str) and quick.strip() else record.summary
    tags = tags_for_record(record)
    tags_line = "<b>Tags:</b> " + " ".join(f"#{_h(t)}" for t in tags) if tags else ""
    header = "<b>Already saved:</b> " + _h(record.title)
    if reason and reason in _DUPLICATE_REASON_TEXT:
        header += f" <i>({_DUPLICATE_REASON_TEXT[reason]})</i>"
    parts = [header, _h(summary)]
    if tags_line:
        parts.append(tags_line)
    parts.append(_cmd("more", record.note_id))
    return "\n\n".join(parts)


def _more_reply(record) -> str:
    s = structured_summary(record)
    generated = record.llm_status == "generated"
    parts: list[str] = [f"<b>{_h(record.title)}</b>"]

    quick = s.get("quick_summary") if generated else None
    if isinstance(quick, str) and quick.strip():
        parts.append(_h(quick.strip()))
    elif record.summary:
        parts.append(_h(record.summary))

    if generated:
        detailed = s.get("detailed_summary")
        if isinstance(detailed, str) and detailed.strip():
            parts.append(_section("Detailed", _h(_shorten(detailed.strip(), 500))))

        claims = s.get("key_claims")
        if isinstance(claims, list):
            lines = [f"- {_h(str(c).strip())}" for c in claims[:5] if str(c).strip()]
            if lines:
                parts.append(_section("Key claims", "\n".join(lines)))

        limitations = s.get("limitations")
        if isinstance(limitations, list):
            lines = [f"- {_h(str(l).strip())}" for l in limitations[:3] if str(l).strip()]
            if lines:
                parts.append(_section("Limitations", "\n".join(lines)))

    scores = scores_for_record(record)
    if scores:
        score_parts = [
            f"{_h(key)} {int(scores[key])}"
            for key in ("relevance", "novelty", "overall")
            if key in scores
        ]
        if score_parts:
            parts.append("<b>Scores:</b> " + " · ".join(score_parts))

    related = related_notes_for_record(record)
    if related:
        rel_lines = [f"- {_h(item['title'])} ({_cmd('more', item['id'])})" for item in related[:5]]
        parts.append(_section("Related", "\n".join(rel_lines)))

    parts.append(f"<b>Source:</b> {_link(record.source_url)}")

    reply = "\n\n".join(parts)
    if len(reply) > 4000:
        reply = reply[:4000].rstrip() + "..."
    return reply


def _status_reply(stats, indexer) -> str:
    lines = [
        f"<b>Notes:</b> {stats.total}",
        f"<b>LLM:</b> {stats.llm_generated} generated, {stats.llm_failed} failed, {stats.llm_skipped} skipped",
        f"<b>Embeddings:</b> {stats.embedding_indexed} indexed, {stats.embedding_failed} failed, {stats.embedding_skipped} skipped",
    ]
    if indexer and indexer.is_configured:
        index_state = "empty" if indexer.index_is_empty() else "ready"
        lines.append(f"<b>Index:</b> {_h(index_state)}")
    else:
        lines.append("<b>Index:</b> not configured (set <code>EMBEDDING_API_KEY</code> and <code>EMBEDDING_MODEL</code>)")
    return "\n".join(lines)


def _retry_failed_reply(result) -> str:
    if result.total == 0:
        return "No failed notes found."
    lines = [
        "<b>Retry complete:</b>",
        f"Checked {result.total}, retried {result.retried}, repaired {result.repaired}, failed {result.failed}, skipped {result.skipped}.",
    ]
    if result.messages:
        lines.append("<b>Details:</b>")
        lines.extend(f"- {_h(message)}" for message in result.messages)
    return "\n".join(lines)


def _recent_reply(records) -> str:
    lines = ["<b>Recent notes:</b>"]
    for r in records:
        date = r.date_saved[:10]
        lines.append(f"<b>{_h(r.title)}</b>\n{_h(r.source_kind)}, {_h(date)}\n{_cmd('more', r.note_id)}")
    return "\n\n".join(lines)


def _tags_list_reply(tag_counts) -> str:
    lines = ["<b>Tags:</b>"]
    for tag, count in tag_counts:
        lines.append(f"#{_h(tag)} ({count})")
    return "\n".join(lines)


def _tags_notes_reply(tag: str, records) -> str:
    lines = [f"<b>Notes tagged #{_h(tag)}:</b>"]
    for r in records:
        lines.append(f"<b>{_h(r.title)}</b>\n{_h(r.source_kind)}, {_h(r.date_saved[:10])}\n{_cmd('more', r.note_id)}")
    return "\n\n".join(lines)


def _related_reply(results, title: str = "Related notes:") -> str:
    lines = [f"<b>{_h(title)}</b>"]
    for item in results:
        summary = _shorten(item.summary, 180)
        lines.append(f"<b>{_h(item.title)}</b> ({item.score:.3f})\n{_h(summary)}\n{_cmd('more', item.note_id)}")
    return "\n\n".join(lines)


def _h(value) -> str:
    return html.escape(str(value), quote=False)


def _cmd(command: str, arg: str | None = None) -> str:
    suffix = f" {_h(arg)}" if arg else ""
    return f"<code>/{_h(command)}{suffix}</code>"


def _section(title: str, body: str) -> str:
    return f"<b>{_h(title)}:</b>\n{body}"


def _link(url: str) -> str:
    escaped = _h(url)
    return f'<a href="{html.escape(str(url), quote=True)}">{escaped}</a>'


_HELP_TEXT = "\n".join(
    ["<b>PRISM commands:</b>", "(send a URL) - save, archive, summarize, and index a link"]
    + [f"<code>/{name}</code> - {_h(desc)}" for name, desc in COMMANDS]
)


def _ask_reply(result, token: str | None = None, offset: int = 0) -> tuple[str, InlineKeyboardMarkup | None]:
    parts = [_h(result.answer)]
    keyboard = None
    if result.sources:
        page = result.sources[offset:offset + PAGE_SIZE]
        more = len(result.sources) > offset + PAGE_SIZE
        lines = [f"- {_h(item.title)} ({_cmd('more', item.note_id)})" for item in page]
        parts.append(_section("Sources", "\n".join(lines)))
        if token:
            keyboard = _semantic_page_keyboard(token, offset, more)
    reply = "\n\n".join(parts)
    if len(reply) > 4000:
        reply = reply[:4000].rstrip() + "..."
    return reply, keyboard


def _idea_reply(record) -> str:
    tags = _json_array(record.tags_json)
    tags_line = "\n<b>Tags:</b> " + " ".join(f"#{_h(t)}" for t in tags) if tags else ""
    return f"<b>Idea:</b> {_h(record.title)}\n{_h(record.summary)}{tags_line}\nRate it below."


def _ideas_list_reply(records) -> str:
    lines = ["<b>Recent ideas:</b>"]
    for r in records:
        rating = _stars(r.rating) if r.rating is not None else "unrated"
        lines.append(f"<b>{_h(r.title)}</b>\n{_h(rating)}, {_h(r.created_at[:10])}")
    return "\n\n".join(lines)


def _semantic_page_view(token: str, title: str, results: list, offset: int) -> tuple[str, InlineKeyboardMarkup | None]:
    offset = max(0, offset)
    page = results[offset:offset + PAGE_SIZE]
    more = len(results) > offset + PAGE_SIZE
    return _related_reply(page, title=title), _semantic_page_keyboard(token, offset, more)


def _semantic_page_keyboard(token: str, offset: int, has_more: bool) -> InlineKeyboardMarkup | None:
    buttons = []
    if offset > 0:
        buttons.append(InlineKeyboardButton("◀ Prev", callback_data=f"sp:{token}:{max(0, offset - PAGE_SIZE)}"))
    if has_more:
        buttons.append(InlineKeyboardButton("Next ▶", callback_data=f"sp:{token}:{offset + PAGE_SIZE}"))
    return InlineKeyboardMarkup([buttons]) if buttons else None


def _parse_semantic_page_callback(data: str | None) -> tuple[str | None, int]:
    if not data:
        return None, 0
    parts = data.split(":", 2)
    if len(parts) != 3 or parts[0] != "sp":
        return None, 0
    try:
        offset = max(0, int(parts[2]))
    except ValueError:
        return None, 0
    return parts[1] or None, offset


def _rating_keyboard(idea_id: str) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(f"★{n}", callback_data=f"idearate:{idea_id}:{n}")
        for n in range(1, 6)
    ]
    return InlineKeyboardMarkup([buttons])


def _ingest_reply(summary) -> str:
    lines = [
        "<b>Feed ingestion complete:</b>",
        f"{summary.feeds} feed(s), {summary.seen} seen, {summary.created} new, {summary.duplicates} duplicates, {summary.failed} failed.",
    ]
    if summary.errors:
        lines.append("<b>Errors:</b>")
        lines.extend(f"- {_h(err)}" for err in summary.errors[:5])
    return "\n".join(lines)


def _traverse_reply(summary, pending: int) -> str:
    return "\n".join([
        "<b>Graph maintenance complete:</b>",
        f"{summary.notes} notes scanned.",
        f"Links: +{summary.links_added} / -{summary.links_removed} across {summary.notes_relinked} note(s).",
        f"Tags: {summary.tags_merged} merged across {summary.notes_retagged} note(s).",
        f"Duplicate merge proposals: {summary.duplicates_proposed} new ({pending} pending — {_cmd('proposals')}).",
    ])


def _proposal_keyboard(proposal_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✓ Approve", callback_data=f"prop:approve:{proposal_id}"),
            InlineKeyboardButton("✗ Reject", callback_data=f"prop:reject:{proposal_id}"),
        ]
    ])


def _parse_proposal_callback(data: str | None) -> tuple[str | None, str | None]:
    if not data:
        return None, None
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != "prop":
        return None, None
    action = parts[1]
    if action not in {"approve", "reject"}:
        return None, None
    proposal_id = parts[2].strip().lower()
    return (action, proposal_id) if proposal_id else (None, None)


def _delete_keyboard(item_type: str, item_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Yes, delete", callback_data=f"delete:{item_type}:{item_id}:yes"),
            InlineKeyboardButton("Cancel", callback_data=f"delete:{item_type}:{item_id}:no"),
        ]
    ])


def _parse_delete_callback(data: str | None) -> tuple[str | None, str | None, bool]:
    if not data:
        return None, None, False
    parts = data.split(":")
    if len(parts) != 4 or parts[0] != "delete":
        return None, None, False
    item_type = parts[1]
    if item_type not in {"note", "idea"}:
        return None, None, False
    item_id = parts[2].strip().lower()
    if not item_id:
        return None, None, False
    return item_type, item_id, parts[3] == "yes"


def _stars(rating: int) -> str:
    return "★" * rating


def _parse_rating_callback(data: str | None) -> tuple[str | None, int | None]:
    if not data:
        return None, None
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != "idearate":
        return None, None
    idea_id = parts[1].strip()
    try:
        rating = int(parts[2])
    except ValueError:
        return None, None
    if not idea_id or not 1 <= rating <= 5:
        return None, None
    return idea_id, rating


def _page_keyboard(kind: str, offset: int, has_more: bool, tag: str | None) -> InlineKeyboardMarkup | None:
    suffix = f":{tag}" if tag else ""
    buttons = []
    if offset > 0:
        buttons.append(InlineKeyboardButton("◀ Prev", callback_data=f"pg:{kind}:{max(0, offset - PAGE_SIZE)}{suffix}"))
    if has_more:
        buttons.append(InlineKeyboardButton("Next ▶", callback_data=f"pg:{kind}:{offset + PAGE_SIZE}{suffix}"))
    return InlineKeyboardMarkup([buttons]) if buttons else None


def _parse_page_callback(data: str | None) -> tuple[str | None, int, str | None]:
    if not data:
        return None, 0, None
    parts = data.split(":", 3)
    if len(parts) < 3 or parts[0] != "pg":
        return None, 0, None
    kind = parts[1]
    try:
        offset = max(0, int(parts[2]))
    except ValueError:
        return None, 0, None
    tag = parts[3] if len(parts) == 4 and parts[3] else None
    return kind, offset, tag


def _shorten(text: str, limit: int) -> str:
    clean = " ".join(text.split())
    if len(clean) <= limit:
        return clean
    return clean[:limit].rstrip() + "..."


async def _post_init(application: Application) -> None:
    await application.bot.set_my_commands([BotCommand(name, desc) for name, desc in COMMANDS])


def build_application(settings: Settings) -> Application:
    bot = PrismBot(settings)
    application = Application.builder().token(settings.telegram_bot_token).post_init(_post_init).build()
    application.add_handler(CommandHandler("start", bot.handle_start))
    application.add_handler(CommandHandler("help", bot.handle_help))
    application.add_handler(CommandHandler("more", bot.handle_more))
    application.add_handler(CommandHandler("rename", bot.handle_rename))
    application.add_handler(CommandHandler("status_set", bot.handle_status_set))
    application.add_handler(CommandHandler("purpose", bot.handle_purpose))
    application.add_handler(CommandHandler("reprocess", bot.handle_reprocess))
    application.add_handler(CommandHandler("reprocess_all", bot.handle_reprocess_all))
    application.add_handler(CommandHandler("repersonalize", bot.handle_repersonalize))
    application.add_handler(CommandHandler("retry_failed", bot.handle_retry_failed))
    application.add_handler(CommandHandler("delete", bot.handle_delete))
    application.add_handler(CommandHandler("wipe_all", bot.handle_wipe_all))
    application.add_handler(CommandHandler("reset_me", bot.handle_reset_me))
    application.add_handler(CommandHandler("update_me", bot.handle_update_me))
    application.add_handler(CommandHandler("related", bot.handle_related))
    application.add_handler(CommandHandler("status", bot.handle_status))
    application.add_handler(CommandHandler("recent", bot.handle_recent))
    application.add_handler(CommandHandler("inbox", bot.handle_inbox))
    application.add_handler(CommandHandler("tags", bot.handle_tags))
    application.add_handler(CommandHandler("find", bot.handle_find))
    application.add_handler(CommandHandler("ask", bot.handle_ask))
    application.add_handler(CommandHandler("idea", bot.handle_idea))
    application.add_handler(CommandHandler("ideas", bot.handle_ideas))
    application.add_handler(CommandHandler("proposals", bot.handle_proposals))
    application.add_handler(CommandHandler("ingest", bot.handle_ingest))
    application.add_handler(CommandHandler("traverse", bot.handle_traverse))
    application.add_handler(CallbackQueryHandler(bot.handle_rating, pattern="^idearate:"))
    application.add_handler(CallbackQueryHandler(bot.handle_proposal_callback, pattern="^prop:"))
    application.add_handler(CallbackQueryHandler(bot.handle_delete_callback, pattern="^delete:"))
    application.add_handler(CallbackQueryHandler(bot.handle_page, pattern="^pg:"))
    application.add_handler(CallbackQueryHandler(bot.handle_semantic_page, pattern="^sp:"))
    application.add_handler(CallbackQueryHandler(bot.handle_save_anyway, pattern="^saveanyway:"))
    application.add_handler(MessageHandler(filters.Document.ALL, bot.handle_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_message))
    return application


def _await_settings(poll_seconds: int = 20) -> Settings:
    """Block until Telegram is configured, so the bot container starts idle
    instead of crash-looping while you finish setup in the web UI.

    Picks up the token/allow-list the moment they appear in env or the runtime
    config store (`runtime/settings.json`), then connects automatically.
    """
    warned = False
    while True:
        try:
            return load_settings()
        except RuntimeError as exc:
            if not warned:
                LOGGER.warning(
                    "Telegram is not configured yet (%s). Waiting — set TELEGRAM_BOT_TOKEN and "
                    "TELEGRAM_ALLOWED_USER_IDS in the web UI (Settings) or .env; the bot will "
                    "connect automatically.",
                    exc,
                )
                warned = True
            time.sleep(poll_seconds)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    settings = _await_settings()
    settings.vault_path.mkdir(parents=True, exist_ok=True)
    settings.archive_path.mkdir(parents=True, exist_ok=True)
    LOGGER.info("Starting PRISM bot with vault at %s, archives at %s, and SQLite at %s", settings.vault_path, settings.archive_path, settings.sqlite_path)
    build_application(settings).run_polling(allowed_updates=Update.ALL_TYPES)
