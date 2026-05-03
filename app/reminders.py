"""Scheduler de recordatorios.

Loop async que cada SCHEDULER_TICK segundos consulta reminders 'pending' con
fire_at <= ahora_utc y dispara mensajes Telegram.
"""
import asyncio
import logging
from datetime import datetime, timezone

from telegram import Bot
from telegram.error import TelegramError

from . import db

log = logging.getLogger("inboxzero.reminders")

SCHEDULER_TICK = 30  # segundos


async def reminder_loop(bot: Bot, stop_event: asyncio.Event) -> None:
    log.info("Reminders scheduler arrancado (tick=%ss).", SCHEDULER_TICK)
    while not stop_event.is_set():
        try:
            await _tick(bot)
        except Exception:
            log.exception("Error en tick de reminders.")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=SCHEDULER_TICK)
        except asyncio.TimeoutError:
            pass
    log.info("Reminders scheduler detenido.")


async def _tick(bot: Bot) -> None:
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    due = db.list_reminders_due(now_iso, limit=20)
    if not due:
        return
    log.info("Disparando %d recordatorio(s).", len(due))
    for r in due:
        try:
            await bot.send_message(
                chat_id=r["chat_id"],
                text=f"⏰ Recordatorio #{r['id']}\n\n{r['text']}",
            )
            db.mark_reminder_fired(r["id"])
        except TelegramError as e:
            log.warning("No pude mandar reminder #%s: %s", r["id"], e)
        except Exception:
            log.exception("Error inesperado disparando reminder #%s", r["id"])
