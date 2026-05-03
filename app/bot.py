"""Handlers de Telegram. Recibe mensajes, clasifica, persiste en SQLite.

v2 agrega: /recordar /recordatorios /cancelar /digest /id
"""
import logging

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from . import classify, config, db, digest, duration

log = logging.getLogger("inboxzero.bot")

WELCOME = (
    "👋 Hola, soy InboxZero.\n\n"
    "Mandame ideas, pedidos, tareas o notas y los guardo en tu second-brain.\n\n"
    "*Captura*\n"
    "/idea <texto> · /pedido <texto> · /tarea <texto> · /nota <texto>\n"
    "(o cualquier mensaje de texto y autoclasifico)\n\n"
    "*Recordatorios*\n"
    "/recordar en 2h llamar a Juan\n"
    "/recordar mañana 9am revisar mail\n"
    "/recordatorios — listar pendientes\n"
    "/cancelar <id> — cancelar uno\n\n"
    "*Otros*\n"
    "/digest — pedirme el resumen ahora\n"
    "/stats — cuántas capturas hay\n"
    "/id — tu user_id y chat_id (útil para configurar)\n"
    "/help — esta ayuda"
)

UNAUTHORIZED = "🚫 Tu user_id no está autorizado. Pedile al admin que te agregue a ALLOWED_USER_IDS."


def _is_authorized(update: Update) -> bool:
    if not update.effective_user:
        return False
    return update.effective_user.id in config.ALLOWED_USER_IDS


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user:
        return
    uid = update.effective_user.id
    if not _is_authorized(update):
        await update.effective_message.reply_text(
            f"{UNAUTHORIZED}\n\nTu user_id es: {uid}"
        )
        return
    await update.effective_message.reply_text(WELCOME, parse_mode="Markdown")


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        await update.effective_message.reply_text(UNAUTHORIZED)
        return
    await update.effective_message.reply_text(WELCOME, parse_mode="Markdown")


async def cmd_id(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_message:
        return
    await update.effective_message.reply_text(
        f"user_id: `{update.effective_user.id}`\nchat_id: `{update.effective_message.chat_id}`",
        parse_mode="Markdown",
    )


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        await update.effective_message.reply_text(UNAUTHORIZED)
        return
    s = db.stats()
    await update.effective_message.reply_text(
        f"📊 Capturas:\n"
        f"• Pendientes de sync: {s['pending']}\n"
        f"• Sincronizadas: {s['synced']}\n"
        f"• Total: {s['total']}\n"
        f"⏰ Recordatorios pendientes: {s.get('reminders_pending', 0)}"
    )


async def cmd_recordar(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        await update.effective_message.reply_text(UNAUTHORIZED)
        return
    msg = update.effective_message
    if not msg or not update.effective_user:
        return
    raw = (msg.text or "").strip()
    # quitar el comando /recordar
    if raw.startswith("/"):
        _, _, raw = raw.partition(" ")
        raw = raw.strip()
    if not raw:
        await msg.reply_text(
            "Uso: `/recordar en 2h <texto>` · `/recordar mañana 9am <texto>`",
            parse_mode="Markdown",
        )
        return
    try:
        fire_at_utc, text = duration.parse_duration(raw)
    except duration.DurationParseError as e:
        await msg.reply_text(f"⚠️ {e}")
        return

    rid = db.insert_reminder(
        chat_id=msg.chat_id,
        user_id=update.effective_user.id,
        text=text,
        fire_at_iso_utc=fire_at_utc.isoformat(timespec="seconds"),
    )
    await msg.reply_text(
        f"⏰ Recordatorio #{rid} programado para *{duration.format_local(fire_at_utc.isoformat())}*.\n\n{text}",
        parse_mode="Markdown",
    )


async def cmd_recordatorios(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        await update.effective_message.reply_text(UNAUTHORIZED)
        return
    if not update.effective_user:
        return
    items = db.list_reminders_pending(user_id=update.effective_user.id, limit=20)
    if not items:
        await update.effective_message.reply_text("✨ Sin recordatorios pendientes.")
        return
    lines = ["⏰ *Recordatorios pendientes:*", ""]
    for r in items:
        when = duration.format_local(r["fire_at"])
        lines.append(f"#{r['id']} · {when}\n{r['text']}\n")
    await update.effective_message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_cancelar(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        await update.effective_message.reply_text(UNAUTHORIZED)
        return
    msg = update.effective_message
    if not msg or not update.effective_user:
        return
    args = ctx.args or []
    if not args:
        await msg.reply_text("Uso: /cancelar <id>")
        return
    try:
        rid = int(args[0])
    except ValueError:
        await msg.reply_text("ID inválido.")
        return
    n = db.cancel_reminder(rid, update.effective_user.id)
    if n == 0:
        await msg.reply_text(f"No encontré un recordatorio pendiente #{rid} tuyo.")
    else:
        await msg.reply_text(f"✓ Recordatorio #{rid} cancelado.")


async def cmd_digest(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        await update.effective_message.reply_text(UNAUTHORIZED)
        return
    if not update.effective_message:
        return
    text = digest.build_digest()
    await update.effective_message.reply_text(text, parse_mode="Markdown")


async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Cualquier mensaje (incluidos /idea, /pedido, /tarea, /nota)."""
    if not update.effective_message or not update.effective_user:
        return
    if not _is_authorized(update):
        await update.effective_message.reply_text(
            f"{UNAUTHORIZED}\n\nTu user_id es: {update.effective_user.id}"
        )
        return

    msg = update.effective_message
    text = msg.text or msg.caption or ""
    if not text.strip():
        await msg.reply_text("⚠️ Mensaje vacío. Mandame texto.")
        return

    category, clean_text = await classify.classify_async(text)

    payload = {
        "message_id": msg.message_id,
        "chat_id": msg.chat_id,
        "user_id": update.effective_user.id,
        "username": update.effective_user.username,
        "date": msg.date.isoformat() if msg.date else None,
        "text": text,
    }

    inserted_id = db.insert_message(
        telegram_msg_id=msg.message_id,
        chat_id=msg.chat_id,
        user_id=update.effective_user.id,
        username=update.effective_user.username,
        text=clean_text,
        classification=category,
        raw_payload=payload,
    )

    if inserted_id is None:
        await msg.reply_text("ℹ️ Ya tenía este mensaje guardado (duplicado).")
        return

    emoji = {"idea": "💡", "pedido": "📨", "tarea": "✅", "nota": "📝"}.get(category, "📥")
    via = "🤖" if config.llm_enabled() else "📐"  # robot=LLM, regla=heurística
    await msg.reply_text(
        f"{emoji} Guardado como *{category}* {via} (id #{inserted_id}).",
        parse_mode="Markdown",
    )


def build_application() -> Application:
    if not config.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN vacío.")

    application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    # Comandos puros
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("id", cmd_id))
    application.add_handler(CommandHandler("stats", cmd_stats))
    application.add_handler(CommandHandler("recordar", cmd_recordar))
    application.add_handler(CommandHandler("recordatorios", cmd_recordatorios))
    application.add_handler(CommandHandler("cancelar", cmd_cancelar))
    application.add_handler(CommandHandler("digest", cmd_digest))

    # Comandos que se persisten como mensajes
    for cmd in ("idea", "pedido", "tarea", "nota"):
        application.add_handler(CommandHandler(cmd, handle_message))

    # Texto sin comando
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    return application
