from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import Forbidden, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .config import Settings
from .db import Database
from .gemini import GeminiError, GeminiFAQClassifier
from .matcher import MatchResult, find_best_match


logger = logging.getLogger(__name__)
NO_TEXT_MESSAGE = "[сообщение без текста]"


def app_db(context: ContextTypes.DEFAULT_TYPE) -> Database:
    return context.application.bot_data["db"]


def app_settings(context: ContextTypes.DEFAULT_TYPE) -> Settings:
    return context.application.bot_data["settings"]


def app_gemini(context: ContextTypes.DEFAULT_TYPE) -> GeminiFAQClassifier | None:
    return context.application.bot_data.get("gemini")


def message_text(update: Update) -> str:
    message = update.effective_message
    if message is None:
        return ""
    if message.text:
        return message.text.strip()
    if message.caption:
        return message.caption.strip()
    return NO_TEXT_MESSAGE


def remember_user(db: Database, update: Update) -> None:
    user = update.effective_user
    if user is None:
        return

    db.upsert_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        language_code=user.language_code,
    )


def user_display(ticket_or_user: dict[str, Any]) -> str:
    parts = [
        ticket_or_user.get("first_name") or "",
        ticket_or_user.get("last_name") or "",
    ]
    name = " ".join(part for part in parts if part).strip()
    username = ticket_or_user.get("username")
    user_id = ticket_or_user.get("user_id")

    if username:
        return f"{name} (@{username}, id {user_id})" if name else f"@{username} (id {user_id})"
    return f"{name} (id {user_id})" if name else f"id {user_id}"


def ticket_keyboard(ticket: dict[str, Any]) -> InlineKeyboardMarkup:
    ticket_id = ticket["id"]
    status = ticket["status"]
    status_button = (
        InlineKeyboardButton("Закрыть", callback_data=f"close:{ticket_id}")
        if status == "open"
        else InlineKeyboardButton("Открыть снова", callback_data=f"reopen:{ticket_id}")
    )

    rows = [
        [
            InlineKeyboardButton("Ответить", callback_data=f"reply:{ticket_id}"),
            InlineKeyboardButton("Показать чат", callback_data=f"history:{ticket_id}"),
        ],
        [status_button],
        [InlineKeyboardButton("Профиль пользователя", url=f"tg://user?id={ticket['user_id']}")],
    ]
    return InlineKeyboardMarkup(rows)


def format_ticket_notification(ticket: dict[str, Any], first_text: str) -> str:
    status = "открыт" if ticket["status"] == "open" else "закрыт"
    return (
        f"Новый вопрос #{ticket['id']} ({status})\n"
        f"Пользователь: {user_display(ticket)}\n\n"
        f"{first_text}\n\n"
        "Кнопка «Ответить» привяжет ваш следующий текст к этому пользователю."
    )


def format_open_tickets(tickets: list[dict[str, Any]]) -> str:
    if not tickets:
        return "Открытых вопросов сейчас нет."

    lines = ["Открытые вопросы:"]
    for ticket in tickets:
        text = (ticket.get("first_text") or "").replace("\n", " ")
        if len(text) > 120:
            text = text[:117] + "..."
        lines.append(f"#{ticket['id']} · {user_display(ticket)} · {text}")
    return "\n".join(lines)


def format_transcript(messages: list[dict[str, Any]]) -> str:
    if not messages:
        return "История чата пока пустая."

    labels = {
        "user": "Пользователь",
        "bot": "Бот",
        "coordinator": "Координатор",
    }
    lines: list[str] = []
    for item in messages:
        label = labels.get(item["direction"], item["direction"])
        ticket = f" #{item['ticket_id']}" if item.get("ticket_id") else ""
        lines.append(f"{item['created_at']} · {label}{ticket}:\n{item['text']}")
    return "\n\n".join(lines)


def split_long_text(text: str, limit: int = 3900) -> list[str]:
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""
    for paragraph in text.split("\n\n"):
        addition = paragraph if not current else "\n\n" + paragraph
        if len(current) + len(addition) <= limit:
            current += addition
            continue

        if current:
            chunks.append(current)
            current = ""

        while len(paragraph) > limit:
            chunks.append(paragraph[:limit])
            paragraph = paragraph[limit:]
        current = paragraph

    if current:
        chunks.append(current)
    return chunks


async def send_chunks(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    text: str,
    reply_to_message_id: int | None = None,
) -> None:
    for chunk in split_long_text(text):
        await context.bot.send_message(
            chat_id=chat_id,
            text=chunk,
            reply_to_message_id=reply_to_message_id,
            disable_web_page_preview=True,
        )
        reply_to_message_id = None


def load_seed(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = app_db(context)
    remember_user(db, update)

    chat = update.effective_chat
    if chat and chat.type != "private":
        await chatid_cmd(update, context)
        return

    await update.effective_message.reply_text(
        "Здравствуйте! Напишите ваш вопрос о Музее Масловки. "
        "Если я не найду готовый ответ, передам сообщение координаторам."
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    settings = app_settings(context)

    if chat and settings.coordinator_chat_id == chat.id:
        await update.effective_message.reply_text(
            "Команды координаторов:\n"
            "/open - открытые вопросы\n"
            "/reply <id> <текст> - ответить пользователю\n"
            "/close <id> [причина] - закрыть вопрос\n"
            "/cancel - отменить режим ответа\n"
            "/chatid - показать id этого чата"
        )
        return

    await update.effective_message.reply_text(
        "Просто напишите вопрос. Я попробую найти ответ в FAQ, "
        "а сложный вопрос передам координаторам музея."
    )


async def chatid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if chat is None:
        return
    await update.effective_message.reply_text(f"ID этого чата: {chat.id}")


async def open_tickets_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_coordinator_chat(update, context):
        return

    tickets = app_db(context).list_open_tickets(limit=30)
    await update.effective_message.reply_text(format_open_tickets(tickets))


async def close_ticket_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_coordinator_chat(update, context):
        return

    if not context.args:
        await update.effective_message.reply_text("Использование: /close <id> [причина]")
        return

    try:
        ticket_id = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text("ID вопроса должен быть числом.")
        return

    reason = " ".join(context.args[1:]).strip() or "closed manually"
    db = app_db(context)
    ticket = db.get_ticket(ticket_id)
    if ticket is None:
        await update.effective_message.reply_text(f"Вопрос #{ticket_id} не найден.")
        return

    db.close_ticket(ticket_id, closed_by_id=update.effective_user.id, reason=reason)
    await update.effective_message.reply_text(f"Вопрос #{ticket_id} закрыт.")


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_coordinator_chat(update, context):
        return

    user = update.effective_user
    chat = update.effective_chat
    if user is None or chat is None:
        return

    app_db(context).clear_coordinator_state(coordinator_id=user.id, chat_id=chat.id)
    await update.effective_message.reply_text("Режим ответа отменен.")


async def reply_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_coordinator_chat(update, context):
        return

    if len(context.args) < 2:
        await update.effective_message.reply_text("Использование: /reply <id> <текст>")
        return

    try:
        ticket_id = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text("ID вопроса должен быть числом.")
        return

    text = " ".join(context.args[1:]).strip()
    await send_coordinator_answer(update, context, ticket_id=ticket_id, text=text)


def is_coordinator_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    settings = app_settings(context)
    chat = update.effective_chat
    return chat is not None and settings.coordinator_chat_id == chat.id


async def private_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if message is None or user is None or chat is None:
        return

    db = app_db(context)
    settings = app_settings(context)
    remember_user(db, update)

    text = message_text(update)
    db_message_id = db.log_message(
        user_id=user.id,
        direction="user",
        text=text,
        tg_chat_id=chat.id,
        tg_message_id=message.message_id,
    )

    if text == NO_TEXT_MESSAGE:
        reply = (
            "Пожалуйста, задайте вопрос текстом. "
            "Стикеры, фото, видео и файлы я не передаю координаторам без текстового вопроса."
        )
        sent = await message.reply_text(reply)
        db.log_message(
            user_id=user.id,
            direction="bot",
            text=reply,
            tg_chat_id=chat.id,
            tg_message_id=sent.message_id,
        )
        logger.info("Ignored non-text private message user=%s db_message_id=%s", user.id, db_message_id)
        return

    match = await choose_faq_match(text, context)

    if match is not None:
        answer = str(match.item["answer"])
        sent = await message.reply_text(answer, disable_web_page_preview=True)
        db.log_message(
            user_id=user.id,
            direction="bot",
            text=answer,
            tg_chat_id=chat.id,
            tg_message_id=sent.message_id,
        )
        logger.info(
            "FAQ match user=%s score=%.3f reason=%s faq_id=%s",
            user.id,
            match.score,
            match.reason,
            match.item.get("id"),
        )
        return

    ticket_id = db.create_ticket(user.id, db_message_id)
    db.attach_message_to_ticket(db_message_id, ticket_id)

    if settings.coordinator_chat_id is None:
        reply = (
            "Я не нашел готовый ответ и сохранил вопрос, "
            "но группа координаторов пока не настроена."
        )
        sent = await message.reply_text(reply)
        db.log_message(
            user_id=user.id,
            ticket_id=ticket_id,
            direction="bot",
            text=reply,
            tg_chat_id=chat.id,
            tg_message_id=sent.message_id,
        )
        return

    try:
        await notify_coordinators(
            update,
            context,
            ticket_id=ticket_id,
            first_text=text,
            source_chat_id=chat.id,
            source_message_id=message.message_id,
        )
        reply = (
            "Спасибо, я передал вопрос координаторам музея. "
            "Ответ придет здесь, в этом чате."
        )
    except TelegramError as exc:
        logger.exception("Could not notify coordinators for ticket %s: %s", ticket_id, exc)
        reply = (
            "Я не нашел готовый ответ и сохранил вопрос, "
            "но сейчас не смог отправить его координаторам. "
            "Пожалуйста, попробуйте позже или свяжитесь с музеем напрямую."
        )

    sent = await message.reply_text(reply)
    db.log_message(
        user_id=user.id,
        ticket_id=ticket_id,
        direction="bot",
        text=reply,
        tg_chat_id=chat.id,
        tg_message_id=sent.message_id,
    )


async def notify_coordinators(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    ticket_id: int,
    first_text: str,
    source_chat_id: int,
    source_message_id: int,
) -> None:
    db = app_db(context)
    settings = app_settings(context)
    ticket = db.get_ticket(ticket_id)
    if ticket is None or settings.coordinator_chat_id is None:
        return

    try:
        await context.bot.forward_message(
            chat_id=settings.coordinator_chat_id,
            from_chat_id=source_chat_id,
            message_id=source_message_id,
        )
    except TelegramError as exc:
        logger.warning("Could not forward message for ticket %s: %s", ticket_id, exc)

    await context.bot.send_message(
        chat_id=settings.coordinator_chat_id,
        text=format_ticket_notification(ticket, first_text),
        reply_markup=ticket_keyboard(ticket),
        disable_web_page_preview=True,
    )


async def choose_faq_match(
    text: str,
    context: ContextTypes.DEFAULT_TYPE,
) -> MatchResult | None:
    if text == NO_TEXT_MESSAGE:
        return None

    db = app_db(context)
    settings = app_settings(context)
    faq_items = db.get_faq_items()
    local_match = find_best_match(
        text,
        faq_items,
        threshold=settings.match_threshold,
    )

    gemini = app_gemini(context)
    if local_match is not None and (
        gemini is None or local_match.score >= settings.local_direct_match_threshold
    ):
        return local_match

    if gemini is None:
        return local_match

    by_intent = {str(item.get("intent")): item for item in faq_items}
    try:
        classification = await gemini.classify(user_message=text, faq_items=faq_items)
    except GeminiError as exc:
        logger.warning("Gemini classification failed, using local fallback: %s", exc)
        return local_match

    logger.info(
        "Gemini classification intent=%s confidence=%.3f reason=%s",
        classification.intent,
        classification.confidence,
        classification.reason,
    )

    if (
        not classification.is_match
        or classification.confidence < settings.gemini_min_confidence
        or classification.intent not in by_intent
    ):
        return None

    return MatchResult(
        item=by_intent[classification.intent],
        score=classification.confidence,
        reason=f"gemini:{classification.reason or 'classified'}",
    )


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return

    if not is_coordinator_chat(update, context):
        await query.answer("Эти кнопки работают только в группе координаторов.", show_alert=True)
        return
    await query.answer()

    try:
        action, raw_ticket_id = query.data.split(":", 1)
        ticket_id = int(raw_ticket_id)
    except ValueError:
        await query.message.reply_text("Не удалось разобрать действие кнопки.")
        return

    db = app_db(context)
    ticket = db.get_ticket(ticket_id)
    if ticket is None:
        await query.message.reply_text(f"Вопрос #{ticket_id} не найден.")
        return

    if action == "reply":
        db.set_coordinator_state(
            coordinator_id=query.from_user.id,
            chat_id=query.message.chat_id,
            ticket_id=ticket_id,
            mode="reply",
        )
        await query.message.reply_text(
            f"Напишите ответ для вопроса #{ticket_id} следующим сообщением. "
            "Если в группе включен privacy mode, отправьте его ответом на это сообщение."
        )
        return

    if action == "history":
        await send_ticket_history(context, chat_id=query.message.chat_id, ticket=ticket)
        return

    if action == "close":
        db.close_ticket(
            ticket_id,
            closed_by_id=query.from_user.id,
            reason="closed by button",
        )
        updated = db.get_ticket(ticket_id)
        await query.edit_message_reply_markup(reply_markup=ticket_keyboard(updated))
        await query.message.reply_text(f"Вопрос #{ticket_id} закрыт.")
        return

    if action == "reopen":
        db.reopen_ticket(ticket_id)
        updated = db.get_ticket(ticket_id)
        await query.edit_message_reply_markup(reply_markup=ticket_keyboard(updated))
        await query.message.reply_text(f"Вопрос #{ticket_id} снова открыт.")
        return

    await query.message.reply_text("Неизвестное действие.")


async def send_ticket_history(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    ticket: dict[str, Any],
) -> None:
    settings = app_settings(context)
    messages = app_db(context).get_transcript(
        ticket["user_id"],
        limit=settings.history_limit,
    )
    header = f"История чата с {user_display(ticket)}:\n\n"
    await send_chunks(context, chat_id=chat_id, text=header + format_transcript(messages))


async def coordinator_group_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not is_coordinator_chat(update, context):
        return

    user = update.effective_user
    chat = update.effective_chat
    if user is None or chat is None:
        return

    db = app_db(context)
    state = db.get_coordinator_state(coordinator_id=user.id, chat_id=chat.id)
    if state is None or state.get("mode") != "reply":
        return

    text = message_text(update)
    await send_coordinator_answer(
        update,
        context,
        ticket_id=int(state["ticket_id"]),
        text=text,
    )
    db.clear_coordinator_state(coordinator_id=user.id, chat_id=chat.id)


async def send_coordinator_answer(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    ticket_id: int,
    text: str,
) -> None:
    db = app_db(context)
    settings = app_settings(context)
    ticket = db.get_ticket(ticket_id)
    message = update.effective_message
    coordinator = update.effective_user

    if message is None or coordinator is None:
        return

    if ticket is None:
        await message.reply_text(f"Вопрос #{ticket_id} не найден.")
        return

    if not text.strip():
        await message.reply_text("Ответ пустой, отправка отменена.")
        return

    user_text = f"Ответ координатора музея:\n\n{text.strip()}"
    try:
        sent = await context.bot.send_message(
            chat_id=ticket["user_id"],
            text=user_text,
            disable_web_page_preview=False,
        )
    except Forbidden:
        await message.reply_text(
            "Не удалось отправить ответ: пользователь заблокировал бота "
            "или удалил чат."
        )
        return
    except TelegramError as exc:
        logger.exception("Could not send coordinator answer: %s", exc)
        await message.reply_text(f"Telegram не принял сообщение: {exc}")
        return

    db.log_message(
        user_id=ticket["user_id"],
        ticket_id=ticket_id,
        direction="coordinator",
        text=text.strip(),
        tg_chat_id=ticket["user_id"],
        tg_message_id=sent.message_id,
        coordinator_id=coordinator.id,
    )

    if settings.auto_close_after_reply:
        db.close_ticket(
            ticket_id,
            closed_by_id=coordinator.id,
            reason="closed after coordinator reply",
        )
        await message.reply_text(f"Ответ отправлен. Вопрос #{ticket_id} закрыт.")
    else:
        await message.reply_text(f"Ответ отправлен. Вопрос #{ticket_id} остался открытым.")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled update error", exc_info=context.error)


def build_application(settings: Settings, db: Database) -> Application:
    application = Application.builder().token(settings.bot_token).build()
    application.bot_data["settings"] = settings
    application.bot_data["db"] = db
    if settings.gemini_enabled and settings.gemini_api_key:
        application.bot_data["gemini"] = GeminiFAQClassifier(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            timeout_seconds=settings.gemini_timeout_seconds,
        )
    else:
        application.bot_data["gemini"] = None

    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("chatid", chatid_cmd))
    application.add_handler(CommandHandler("open", open_tickets_cmd))
    application.add_handler(CommandHandler("close", close_ticket_cmd))
    application.add_handler(CommandHandler("reply", reply_cmd))
    application.add_handler(CommandHandler("cancel", cancel_cmd))
    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, private_message))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, coordinator_group_message))
    application.add_error_handler(error_handler)
    return application


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    settings = Settings.from_env()
    db = Database(settings.database_path)
    db.init()

    if db.faq_count() == 0 and settings.faq_seed_path.exists():
        count = db.seed_faq(load_seed(settings.faq_seed_path))
        logger.info("Seeded %s FAQ items from %s", count, settings.faq_seed_path)

    if settings.coordinator_chat_id is None:
        logger.warning("COORDINATOR_CHAT_ID is not set. /chatid still works.")
    if settings.gemini_enabled and not settings.gemini_api_key:
        logger.warning("GEMINI_ENABLED is true, but GEMINI_API_KEY is not set.")

    build_application(settings, db).run_polling(allowed_updates=Update.ALL_TYPES)
