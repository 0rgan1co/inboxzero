"""Handlers de Telegram. Recibe mensajes, clasifica, persiste en SQLite.

v2: /recordar /recordatorios /cancelar /digest /id
v3: handler para audios/voz → Whisper local → captura tipo idea
v3.1: /inbox (resumen agrupado) y /procesar (triage con botones inline)
"""
import logging
import os
import tempfile

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from . import classify, config, db, digest, duration, transcribe, triage

log = logging.getLogger("inboxzero.bot")

WELCOME = (
    "👋 Hola, soy InboxZero.\n\n"
    "Mandame ideas, pedidos, tareas, notas o audios y los guardo en tu second-brain.\n\n"
    "*Captura*\n"
    "/idea <texto> · /pedido <texto> · /tarea <texto> · /nota <texto>\n"
    "(o cualquier mensaje de texto y autoclasifico — los audios se transcriben)\n\n"
    "*Inbox y triage*\n"
    "/inbox — resumen de pendientes agrupados por tipo\n"
    "/procesar — triagear pending: derivar a agente / guardar / descartar\n\n"
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


async def cmd_inbox(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Resumen de capturas pending agrupadas por tipo."""
    if not _is_authorized(update):
        await update.effective_message.reply_text(UNAUTHORIZED)
        return
    items = db.list_pending(limit=200)
    if not items:
        await update.effective_message.reply_text(
            "✨ *Inbox vacío.*\nNo hay capturas pendientes.",
            parse_mode="Markdown",
        )
        return

    by_type: dict[str, list[dict]] = {}
    for it in items:
        by_type.setdefault(it["classification"], []).append(it)

    emoji = {"idea": "💡", "pedido": "📨", "tarea": "✅", "nota": "📝"}
    section_order = ["tarea", "pedido", "idea", "nota"]
    lines: list[str] = [f"📥 *Inbox: {len(items)} pendiente{'s' if len(items) != 1 else ''}*", ""]

    for cat in section_order:
        bucket = by_type.get(cat, [])
        if not bucket:
            continue
        em = emoji.get(cat, "📥")
        lines.append(f"{em} *{cat.capitalize()}s ({len(bucket)})*")
        for it in bucket[:8]:  # cap 8 por sección para no explotar el mensaje
            txt = (it["text"] or "").replace("\n", " ").strip()
            if len(txt) > 80:
                txt = txt[:77] + "..."
            triage_tag = ""
            if it.get("triage_decision"):
                tag_emoji = {"derivar": "🚀", "guardar": "💾", "descartar": "🗑"}.get(
                    it["triage_decision"], "🏷"
                )
                triage_tag = f" {tag_emoji}"
            lines.append(f"  `#{it['id']}`{triage_tag} {txt}")
        if len(bucket) > 8:
            lines.append(f"  _... y {len(bucket) - 8} más._")
        lines.append("")

    # Totales triage
    triaged = sum(1 for it in items if it.get("triage_decision"))
    if triaged:
        lines.append(f"_{triaged}/{len(items)} ya triageadas. Faltan {len(items) - triaged}._")
    lines.append("")
    lines.append("Comandos: /procesar para triagear · /stats para más detalle")

    await update.effective_message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
    )


def _triage_kbd(msg_id: int, suggested_agent: str | None) -> InlineKeyboardMarkup:
    """Botones inline: derivar (con sugerencia si hay) / guardar / descartar."""
    rows: list[list[InlineKeyboardButton]] = []
    if suggested_agent:
        em = triage.emoji_for_agent(suggested_agent)
        rows.append([
            InlineKeyboardButton(
                f"🚀 Derivar a {em} {suggested_agent}",
                callback_data=f"triage:{msg_id}:derivar:{suggested_agent}",
            )
        ])
    else:
        # Sin sugerencia: ofrecer los 3 agentes manualmente
        rows.append([
            InlineKeyboardButton("🐒 tres-monos",  callback_data=f"triage:{msg_id}:derivar:tres-monos"),
            InlineKeyboardButton("🟡 res-non-verba", callback_data=f"triage:{msg_id}:derivar:res-non-verba"),
        ])
        rows.append([
            InlineKeyboardButton("🐦 colibri", callback_data=f"triage:{msg_id}:derivar:colibri"),
        ])
    rows.append([
        InlineKeyboardButton("💾 Guardar",   callback_data=f"triage:{msg_id}:guardar:"),
        InlineKeyboardButton("🗑 Descartar", callback_data=f"triage:{msg_id}:descartar:"),
    ])
    return InlineKeyboardMarkup(rows)


async def cmd_procesar(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Triagea las capturas pending NO triageadas todavía. Manda un mensaje por captura con botones."""
    if not _is_authorized(update):
        await update.effective_message.reply_text(UNAUTHORIZED)
        return

    all_pending = db.list_pending(limit=200)
    untriaged = [it for it in all_pending if not it.get("triage_decision")]

    if not untriaged:
        await update.effective_message.reply_text(
            "✨ *Nada para triagear.*\n"
            f"_{len(all_pending)} captura(s) pending, todas ya con decisión._",
            parse_mode="Markdown",
        )
        return

    # Header
    auto = sum(1 for it in untriaged if triage.suggest_agent(it["text"], it["classification"]))
    manual = len(untriaged) - auto
    await update.effective_message.reply_text(
        f"🛂 *Triage: {len(untriaged)} captura{'s' if len(untriaged) != 1 else ''}*\n"
        f"• 🤖 Auto-derivables (sugerencia): *{auto}*\n"
        f"• 🤔 Requieren tu decisión: *{manual}*\n\n"
        f"Te muestro de a una. Cliqueá un botón.",
        parse_mode="Markdown",
    )

    # Limit a 10 por corrida para no spamear
    LIMIT = 10
    for it in untriaged[:LIMIT]:
        suggested = triage.suggest_agent(it["text"], it["classification"])
        emoji_cat = {"idea": "💡", "pedido": "📨", "tarea": "✅", "nota": "📝"}.get(
            it["classification"], "📥"
        )
        text = it["text"].strip()
        if len(text) > 350:
            text = text[:347] + "..."

        if suggested:
            sug_line = f"\n_Sugerencia: derivar a {triage.emoji_for_agent(suggested)} *{suggested}*_"
        else:
            sug_line = "\n_Sin sugerencia automática — vos decidís._"

        msg_text = (
            f"{emoji_cat} *Captura #{it['id']}* · {it['classification']}\n\n"
            f"{text}\n{sug_line}"
        )
        try:
            await update.effective_message.reply_text(
                msg_text,
                parse_mode="Markdown",
                reply_markup=_triage_kbd(it["id"], suggested),
            )
        except Exception:
            log.exception("Error mostrando captura #%s en /procesar", it["id"])

    if len(untriaged) > LIMIT:
        await update.effective_message.reply_text(
            f"_Mostré las primeras {LIMIT}. Quedan {len(untriaged) - LIMIT} sin triagear. "
            f"Volvé a correr /procesar después de decidir estas._",
            parse_mode="Markdown",
        )


async def on_triage_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """CallbackQueryHandler: procesa los clicks de los botones de /procesar."""
    q = update.callback_query
    if not q or not q.data:
        return
    if not _is_authorized(update):
        await q.answer("No autorizado.", show_alert=True)
        return

    # Parse callback_data: "triage:{msg_id}:{decision}:{target?}"
    parts = q.data.split(":", 3)
    if len(parts) < 3 or parts[0] != "triage":
        await q.answer("Callback inválido.")
        return

    try:
        msg_id = int(parts[1])
    except ValueError:
        await q.answer("ID inválido.")
        return
    decision = parts[2]
    target = parts[3] if len(parts) > 3 and parts[3] else None

    if decision not in ("derivar", "guardar", "descartar"):
        await q.answer("Decisión inválida.")
        return

    msg = db.get_message(msg_id)
    if not msg:
        await q.answer("Captura no encontrada.")
        return

    db.set_triage(msg_id, decision=decision, target=target)

    confirm_emoji = {"derivar": "🚀", "guardar": "💾", "descartar": "🗑"}[decision]
    if decision == "derivar" and target:
        confirmation = (
            f"{confirm_emoji} *Captura #{msg_id} → {triage.emoji_for_agent(target)} {target}*\n\n"
            f"Marcada para derivación. Aparecerá en el sync con la metadata.\n"
            f"_(la integración real con el agente la activamos después)_"
        )
    elif decision == "guardar":
        confirmation = (
            f"{confirm_emoji} *Captura #{msg_id} guardada para después.*\n"
            f"Sigue en el inbox. Sincronizada al vault con la marca."
        )
    else:  # descartar
        confirmation = (
            f"{confirm_emoji} *Captura #{msg_id} descartada.*\n"
            f"Marcada como descartada. Aparecerá en el sync con la marca; vos podés borrarla del vault."
        )

    # Editar el mensaje original removiendo botones
    try:
        await q.edit_message_text(confirmation, parse_mode="Markdown")
    except Exception:
        # Si no se puede editar, mandar como respuesta nueva
        await q.message.reply_text(confirmation, parse_mode="Markdown")

    await q.answer("Decisión registrada.")


async def handle_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler para nota de voz / audio file → transcribe con Whisper local."""
    if not update.effective_message or not update.effective_user:
        return
    if not _is_authorized(update):
        await update.effective_message.reply_text(
            f"{UNAUTHORIZED}\n\nTu user_id es: {update.effective_user.id}"
        )
        return

    msg = update.effective_message
    voice = msg.voice or msg.audio
    if not voice:
        return

    if not transcribe.is_ready():
        await msg.reply_text(
            "⚠️ Whisper no está disponible. "
            "Verificá WHISPER_ENABLED y los logs del container."
        )
        return

    duration_s = voice.duration or 0
    status = await msg.reply_text(
        f"🎙️ Transcribiendo {'nota de voz' if msg.voice else 'audio'} "
        f"({duration_s}s)... esto puede tardar."
    )

    tmp_path = None
    try:
        # Descargar archivo de Telegram
        tg_file = await voice.get_file()
        suffix = ".ogg" if msg.voice else (".m4a" if msg.audio else ".bin")
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False, dir="/tmp") as tmp:
            tmp_path = tmp.name
        await tg_file.download_to_drive(tmp_path)

        # Transcribir (corre en thread pool, no bloquea otros mensajes)
        text = await transcribe.transcribe(tmp_path)
    except Exception as exc:
        log.exception("Error transcribiendo audio: %s", exc)
        await status.edit_text(f"❌ Error transcribiendo: {exc}")
        return
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    if not text:
        await status.edit_text("⚠️ No pude transcribir nada. Audio vacío o no entendible.")
        return

    # Guardar como captura tipo "idea"
    payload = {
        "message_id": msg.message_id,
        "chat_id": msg.chat_id,
        "user_id": update.effective_user.id,
        "username": update.effective_user.username,
        "date": msg.date.isoformat() if msg.date else None,
        "voice_duration_s": duration_s,
        "voice_file_id": voice.file_id,
        "voice_mime_type": getattr(voice, "mime_type", None),
        "transcribed_text": text,
        "whisper_model": config.WHISPER_MODEL,
    }

    inserted_id = db.insert_message(
        telegram_msg_id=msg.message_id,
        chat_id=msg.chat_id,
        user_id=update.effective_user.id,
        username=update.effective_user.username,
        text=text,
        classification="idea",
        raw_payload=payload,
    )

    if inserted_id is None:
        await status.edit_text(
            f"🎙️ Transcripto, pero ya tenía este mensaje guardado.\n\n_Texto:_\n{text}",
            parse_mode="Markdown",
        )
        return

    # Reply con la transcripción + confirmación
    await status.edit_text(
        f"💡🎙️ Audio transcripto y guardado como *idea* (id #{inserted_id}).\n\n"
        f"_Transcripción ({config.WHISPER_MODEL}, {duration_s}s):_\n\n{text}",
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
    # v3.1
    application.add_handler(CommandHandler("inbox", cmd_inbox))
    application.add_handler(CommandHandler("procesar", cmd_procesar))
    application.add_handler(CallbackQueryHandler(on_triage_callback, pattern=r"^triage:"))

    # Comandos que se persisten como mensajes
    for cmd in ("idea", "pedido", "tarea", "nota"):
        application.add_handler(CommandHandler(cmd, handle_message))

    # v3: voz / audio → Whisper local
    application.add_handler(
        MessageHandler(filters.VOICE | filters.AUDIO, handle_voice)
    )

    # Texto sin comando
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    return application
