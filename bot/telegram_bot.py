"""Telegram front end. Thin handlers over the API; formatting lives in pure functions so it's testable.

Privacy: never logs message text, usernames or chat IDs. A pending Instagram link is kept only in
memory (chat_data, no persistence) for at most 10 minutes.
"""
import html
import logging
import time

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler,
                          filters)

from app.config import get_settings
from app.instagram import find_instagram_url

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # httpx logs URLs, which include the bot token
log = logging.getLogger("fcc.bot")

PENDING_TTL = 10 * 60
MAX_SOURCES = 3

WELCOME = (
    "👋 <b>Fact-Check Coach</b>\n\n"
    "Send me a post you're not sure about: paste the caption, or share an Instagram post straight to me.\n\n"
    "Before I show you anything, I'll ask <b>you</b> to guess. Then you'll see what 6 named news outlets "
    "say, with quotes checked word for word. The goal: you need me less every time.\n\n"
    "🔒 I don't store your messages, your username or this chat."
)
VERDICTS = {
    "false": ("❌", "False"),
    "true": ("✅", "True"),
    "misleading": ("⚠️", "Misleading"),
    "unverified": ("❓", "Unverified"),
    "developing": ("⏳", "Still developing"),
    "opinion": ("💬", "Opinion"),
}
GUESS_LABELS = {"true": "True", "false": "False", "not_sure": "Not sure"}


def e(s: object) -> str:
    return html.escape(str(s), quote=False)


def agreement_text(verdict: str, a: dict) -> str:
    covering = a["supports"] + a["contradicts"]
    total = a["outlets_checked"]
    if covering == 0:
        return f"None of the {total} outlets we checked cover it yet."
    def say(n: int) -> str:
        return f"{n} says" if n == 1 else f"{n} say"

    head = f"{covering} of {total} outlets checked cover it"
    if verdict in ("false", "true") and min(a["supports"], a["contradicts"]) == 0:
        return f"{head}; {'all ' if covering > 1 else ''}{say(covering)} it's {verdict}."
    return f"{head}: {say(a['contradicts'])} it's false, {say(a['supports'])} it's true."


def format_start(payload: dict) -> str:
    return (f"🔎 <b>The claim:</b> {e(payload['claim'])}\n\n"
            f"🤔 {e(payload['question'])}\n\n"
            "<b>What's your guess?</b>")


def format_reveal(payload: dict) -> str:
    emoji, label = VERDICTS.get(payload["verdict"], ("•", payload["verdict"]))
    lines = [f"{emoji} <b>{e(label)}</b>  ·  confidence: {e(payload['confidence'])}"]
    if payload.get("guess_feedback"):
        lines += ["", f"🎯 {e(payload['guess_feedback'])}"]
    lines += ["", e(payload["explanation"])]
    if payload["verdict"] != "opinion":
        lines += ["", f"📊 {e(agreement_text(payload['verdict'], payload['agreement']))}"]

    seen, shown = set(), []
    for s in payload.get("sources", []):
        if s["outlet"] not in seen and len(shown) < MAX_SOURCES:
            seen.add(s["outlet"])
            shown.append(s)
    if shown:
        lines += ["", "<b>Sources</b>"]
        for s in shown:
            detail = f"“{e(s['quote'])}”" if s.get("quote") else (f"Rated: {e(s['rating'])}" if s.get("rating") else "")
            lines.append(f"• <a href=\"{html.escape(s['url'])}\">{e(s['outlet'])}</a> ({e(s['stance'])}) {detail}".rstrip())

    rejected = payload["agreement"].get("rejected_quotes", 0)
    if rejected:
        plural = rejected > 1
        lines += ["", f"🛡 {rejected} AI-suggested quote{'s' if plural else ''} didn't match the source "
                      f"and {'were' if plural else 'was'} thrown out."]
    lines += ["", f"💡 <b>Tip:</b> {e(payload['tip'])}", "", f"<i>{e(payload['disclaimer'])}</i>"]
    return "\n".join(lines)


def guess_keyboard(check_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=f"g|{check_id}|{g}")
                                  for g, label in GUESS_LABELS.items()]])


class ApiClient:
    def __init__(self, base_url: str) -> None:
        self.http = httpx.AsyncClient(base_url=base_url, timeout=30)

    async def start(self, text: str, url: str | None) -> dict:
        r = await self.http.post("/check/start", json={"text": text, "url": url, "client": "telegram"})
        r.raise_for_status()
        return r.json()

    async def reveal(self, check_id: str, guess: str) -> httpx.Response:
        return await self.http.post("/check/reveal", json={"check_id": check_id, "guess": guess})


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(WELCOME, parse_mode=ParseMode.HTML)


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    text = (msg.text or msg.caption or "").strip()
    api: ApiClient = context.bot_data["api"]

    url = find_instagram_url(text)
    pending = context.chat_data.pop("pending_ig", None)
    if not url and pending and time.time() - pending[1] < PENDING_TTL:
        url = pending[0]  # the user is replying with the caption we asked for
    if url and text.strip() == url:
        text = ""

    await msg.chat.send_action("typing")
    try:
        payload = await api.start(text, url)
    except httpx.HTTPStatusError as err:
        log.warning("start failed with status %s", err.response.status_code)
        await msg.reply_text("Hmm, I couldn't read that. Try pasting the post's text.")
        return
    except httpx.HTTPError as err:
        log.warning("start failed: %s", type(err).__name__)
        await msg.reply_text("I can't reach the checker right now. Please try again in a minute.")
        return

    if payload.get("needs_text"):
        if url:
            context.chat_data["pending_ig"] = (url, time.time())
        await msg.reply_text(payload["note"])
        return
    if not payload["checkable"]:
        await msg.reply_text(f"💬 {payload['note']}")
        return
    await msg.reply_text(format_start(payload), parse_mode=ParseMode.HTML,
                         reply_markup=guess_keyboard(payload["check_id"]))


async def on_guess(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    try:
        _, check_id, guess = query.data.split("|")
    except ValueError:
        return
    api: ApiClient = context.bot_data["api"]
    try:
        r = await api.reveal(check_id, guess)
    except httpx.HTTPError as err:
        log.warning("reveal failed: %s", type(err).__name__)
        await query.message.reply_text("I can't reach the checker right now. Please try again in a minute.")
        return
    if r.status_code in (404, 410):
        await query.edit_message_reply_markup(None)
        await query.message.reply_text("That check has expired. Send me the post again.")
        return
    if r.status_code != 200:
        await query.message.reply_text("Something went wrong on my side. Please try again.")
        return
    await query.edit_message_reply_markup(None)
    await query.message.reply_text(f"You guessed: <b>{GUESS_LABELS[guess]}</b>", parse_mode=ParseMode.HTML)
    await query.message.reply_text(format_reveal(r.json()), parse_mode=ParseMode.HTML,
                                   disable_web_page_preview=True)


def main() -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN in .env (get one from @BotFather).")
    app = Application.builder().token(settings.telegram_bot_token).build()
    app.bot_data["api"] = ApiClient(settings.api_base_url)
    app.add_handler(CommandHandler(["start", "help"], cmd_start))
    app.add_handler(CallbackQueryHandler(on_guess, pattern=r"^g\|"))
    app.add_handler(MessageHandler((filters.TEXT | filters.CAPTION) & ~filters.COMMAND, on_message))
    log.info("bot running against %s", settings.api_base_url)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
