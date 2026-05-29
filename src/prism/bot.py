from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from prism.config import Settings, load_settings
from prism.db import PrismDatabase
from prism.notes import NoteService, extract_first_url

LOGGER = logging.getLogger(__name__)


class PrismBot:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.database = PrismDatabase(settings.sqlite_path)
        self.notes = NoteService(settings.vault_path, self.database)

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
            reply = f"Saved: {record.title}\n{record.summary}\n/more {record.note_id}"
        else:
            reply = f"Already saved: {record.title}\n{record.summary}\n/more {record.note_id}"
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
            f"{record.summary}\n"
            f"Status: {record.status}\n"
            f"Path: {record.note_path}\n"
            f"Source: {record.source_url}"
        )

    async def handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        if not await self._is_allowed(update):
            return
        if update.effective_message:
            await update.effective_message.reply_text("Send a URL to save a PRISM placeholder note.")

    async def _is_allowed(self, update: Update) -> bool:
        user = update.effective_user
        if user and user.id in self.settings.telegram_allowed_user_ids:
            return True
        LOGGER.warning("Rejected unauthorized Telegram user: %s", user.id if user else "unknown")
        if update.effective_message:
            await update.effective_message.reply_text("Unauthorized.")
        return False


def build_application(settings: Settings) -> Application:
    bot = PrismBot(settings)
    application = Application.builder().token(settings.telegram_bot_token).build()
    application.add_handler(CommandHandler("start", bot.handle_start))
    application.add_handler(CommandHandler("more", bot.handle_more))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_message))
    return application


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = load_settings()
    settings.vault_path.mkdir(parents=True, exist_ok=True)
    LOGGER.info("Starting PRISM bot with vault at %s and SQLite at %s", settings.vault_path, settings.sqlite_path)
    build_application(settings).run_polling(allowed_updates=Update.ALL_TYPES)
