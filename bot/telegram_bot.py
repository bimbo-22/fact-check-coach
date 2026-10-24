"""Telegram front end. Thin handlers over the API; formatting lives in pure functions so it's testable.

Privacy: never logs message text, usernames or chat IDs. A pending Instagram link is kept only in
memory (chat_data, no persistence) for at most 10 minutes.
"""
import base64
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
    "Send me a post you're not sure about: paste the caption, share an Instagram post straight to me, "
    "or send a <b>screenshot</b>.\n\n"
    "Before I show you anything, I'll ask <b>you</b> to guess. Then you'll see what 6 named news outlets "
    "say, with quotes checked word for word. The goal: you need me less every time.\n\n"
    "🗨 Want to know which comments to trust? Send /comments, then paste or screenshot them.\n\n"
    "🔒 I don't store your messages, your screenshots, your username or this chat."
)
COMMENT_ICONS = {"opinion": "💬", "question": "❔", "other": "▫️"}
VERDICT_COMMENT_ICONS = {"false": "🚩", "true": "✅", "misleading": "⚠️", "unverified": "❓", "developing": "⏳"}
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


def format_comments(payload: dict) -> str:
    if not payload.get("comments"):
        return e(payload.get("note") or "I couldn't find any comments in that.")
    sm = payload["summary"]
    lines = [f"🗨 <b>Comment check</b>: {sm['opinions']} opinion{'s' * (sm['opinions'] != 1)}, "
             f"{sm['claims']} factual claim{'s' * (sm['claims'] != 1)}, {sm['questions']} question{'s' * (sm['questions'] != 1)}"]
    if sm["misinformation"]:
        lines.append(f"🚩 <b>{sm['misinformation']} spread{'s' * (sm['misinformation'] == 1)} misinformation</b>")
    if sm["backed"]:
        lines.append(f"✅ <b>{sm['backed']} {'is' if sm['backed'] == 1 else 'are'} backed by the sources</b>")
    lines.append("")
    for c in payload["comments"]:
        icon = VERDICT_COMMENT_ICONS.get(c.get("verdict")) or COMMENT_ICONS.get(c["kind"], "▫️")
        text = c["text"] if len(c["text"]) <= 120 else c["text"][:117] + "…"
        lines.append(f"{icon} “{e(text)}”\n    <i>{e(c['label'])}</i>")
        if c.get("source") and c.get("verdict") in ("false", "true", "misleading"):
            s_ = c["source"]
            lines.append(f"    ↳ <a href=\"{html.escape(s_['url'])}\">{e(s_['outlet'])}</a>")
    lines += ["", f"💡 <b>Tip:</b> {e(payload['tip'])}", "", f"<i>{e(payload['disclaimer'])}</i>"]
    return "\n".join(lines)


def comments_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🗨 Check the comments too", callback_data="comments")]])


def guess_keyboard(check_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=f"g|{check_id}|{g}")
                                  for g, label in GUESS_LABELS.items()]])


class ApiClient:
    def __init__(self, base_url: str) -> None:
        self.http = httpx.AsyncClient(base_url=base_url, timeout=30)

    async def start(self, text: str, url: str | None, image_b64: str | None = None) -> dict:
        r = await self.http.post("/check/start", json={"text": text, "url": url, "image_base64": image_b64,
                                                       "client": "telegram"})
        r.raise_for_status()
        return r.json()

    async def comments(self, text: str, image_b64: str | None = None) -> dict:
        r = await self.http.post("/comments/check", json={"text": text, "image_base64": image_b64,
                                                          "client": "telegram"})
        r.raise_for_status()
        return r.json()

    async def reveal(self, check_id: str, guess: str) -> httpx.Response:
        return await self.http.post("/check/reveal", json={"check_id": check_id, "guess": guess})


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(WELCOME, parse_mode=ParseMode.HTML)


async def cmd_comments(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.chat_data["comments_mode"] = time.time()
    await update.effective_message.reply_text(
        "🗨 Paste the comments (one per line is best) or send a screenshot of them. "
        "I'll label opinions, flag misinformation and point out the comments the sources back up.")


async def on_comments_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    await cmd_comments(update, context)


async def photo_b64(msg) -> str | None:
    """Largest size of a sent photo (or image document), base64. Kept in memory only for this request."""
    if msg.photo:
        f = await msg.photo[-1].get_file()
    elif msg.document and (msg.document.mime_type or "").startswith("image/"):
        f = await msg.document.get_file()
    else:
        return None
    return base64.b64encode(bytes(await f.download_as_bytearray())).decode()


async def check_comments(msg, api: ApiClient, text: str, image_b64: str | None) -> None:
    await msg.chat.send_action("typing")
    try:
        payload = await api.comments(text, image_b64)
    except httpx.HTTPError as err:
        log.warning("comments failed: %s", type(err).__name__)
        await msg.reply_text("I couldn't check those comments. Try pasting them as text, one per line.")
        return
    await msg.reply_text(format_comments(payload), parse_mode=ParseMode.HTML, disable_web_page_preview=True)


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    text = (msg.text or msg.caption or "").strip()
    api: ApiClient = context.bot_data["api"]
    image_b64 = await photo_b64(msg)

    mode = context.chat_data.pop("comments_mode", None)
    if mode and time.time() - mode < PENDING_TTL:
        await check_comments(msg, api, text, image_b64)
        return

    url = find_instagram_url(text)
    pending = context.chat_data.pop("pending_ig", None)
    if not url and pending and time.time() - pending[1] < PENDING_TTL:
        url = pending[0]  # the user is replying with the caption we asked for
    if url and text.strip() == url:
        text = ""

    if not text and not url and not image_b64:
        await msg.reply_text("Send me a caption, an Instagram link or a screenshot to check.")
        return
    await msg.chat.send_action("typing")
    try:
        payload = await api.start(text, url, image_b64)
    except httpx.HTTPStatusError as err:
        log.warning("start failed with status %s", err.response.status_code)
        await msg.reply_text("Hmm, I couldn't read that. Try pasting the post's text, or a clearer screenshot.")
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
                                   disable_web_page_preview=True, reply_markup=comments_keyboard())


def main() -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN in .env (get one from @BotFather).")
    app = Application.builder().token(settings.telegram_bot_token).build()
    app.bot_data["api"] = ApiClient(settings.api_base_url)
    app.add_handler(CommandHandler(["start", "help"], cmd_start))
    app.add_handler(CommandHandler("comments", cmd_comments))
    app.add_handler(CallbackQueryHandler(on_guess, pattern=r"^g\|"))
    app.add_handler(CallbackQueryHandler(on_comments_button, pattern=r"^comments$"))
    app.add_handler(MessageHandler((filters.TEXT | filters.CAPTION | filters.PHOTO | filters.Document.IMAGE)
                                   & ~filters.COMMAND, on_message))
    log.info("bot running against %s", settings.api_base_url)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
