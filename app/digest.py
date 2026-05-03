"""Digest diario.

Loop async que cada minuto verifica si la hora local actual es DIGEST_HOUR:DIGEST_MINUTE
y, si sí, manda un resumen al DIGEST_CHAT_ID. Para evitar mandar dos veces el mismo día,
guardamos en memoria el último día disparado.
"""
import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import Bot
from telegram.error import TelegramError

from . import config, db, duration

log = logging.getLogger("inboxzero.digest")

TICK = 30  # segundos


def build_digest() -> str:
    s = db.stats()
    pending_msgs = db.list_pending(limit=20)
    pending_reminders = db.list_reminders_pending(limit=10)

    lines: list[str] = []
    lines.append("☀️ *Digest InboxZero*")
    lines.append("")
    lines.append(f"📥 Capturas pendientes de sync: *{s['pending']}*")
    lines.append(f"📤 Sincronizadas históricamente: {s['synced']}")
    lines.append(f"🗂️ Total: {s['total']}")
    lines.append(f"⏰ Recordatorios pendientes: *{s.get('reminders_pending', 0)}*")
    lines.append("")

    if pending_msgs:
        lines.append("*Capturas recientes pending:*")
        for m in pending_msgs[:5]:
            text = m["text"].replace("\n", " ")
            if len(text) > 80:
                text = text[:77] + "..."
            emoji = {"idea": "💡", "pedido": "📨", "tarea": "✅", "nota": "📝"}.get(m["classification"], "📥")
            lines.append(f"{emoji} #{m['id']} {text}")
        if len(pending_msgs) > 5:
            lines.append(f"_... y {len(pending_msgs) - 5} más._")
        lines.append("")

    if pending_reminders:
        lines.append("*Próximos recordatorios:*")
        for r in pending_reminders[:5]:
            text = r["text"].replace("\n", " ")
            if len(text) > 60:
                text = text[:57] + "..."
            when = duration.format_local(r["fire_at"])
            lines.append(f"⏰ #{r['id']} {when} — {text}")
        if len(pending_reminders) > 5:
            lines.append(f"_... y {len(pending_reminders) - 5} más._")
        lines.append("")

    if not pending_msgs and not pending_reminders:
        lines.append("✨ Nada pendiente. Inbox limpio.")

    return "\n".join(lines)


async def send_digest(bot: Bot, chat_id: int) -> bool:
    text = build_digest()
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
        return True
    except TelegramError as e:
        log.warning("No pude mandar digest: %s", e)
        return False


async def digest_loop(bot: Bot, stop_event: asyncio.Event) -> None:
    if not config.DIGEST_ENABLED:
        log.info("Digest deshabilitado (DIGEST_ENABLED=false). Loop no arranca.")
        return
    if config.DIGEST_CHAT_ID == 0:
        log.warning("DIGEST_ENABLED=true pero DIGEST_CHAT_ID=0. Loop no arranca.")
        return

    tz = ZoneInfo(config.DIGEST_TZ)
    last_sent_day: str | None = None
    log.info(
        "Digest scheduler arrancado: %02d:%02d %s al chat %s",
        config.DIGEST_HOUR, config.DIGEST_MINUTE, config.DIGEST_TZ, config.DIGEST_CHAT_ID,
    )

    while not stop_event.is_set():
        try:
            now = datetime.now(tz)
            day_key = now.strftime("%Y-%m-%d")
            if (
                now.hour == config.DIGEST_HOUR
                and now.minute >= config.DIGEST_MINUTE
                and last_sent_day != day_key
            ):
                ok = await send_digest(bot, config.DIGEST_CHAT_ID)
                if ok:
                    last_sent_day = day_key
                    log.info("Digest enviado para %s.", day_key)
        except Exception:
            log.exception("Error en tick de digest.")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=TICK)
        except asyncio.TimeoutError:
            pass

    log.info("Digest scheduler detenido.")
