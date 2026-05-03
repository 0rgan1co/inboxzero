"""Entrypoint: FastAPI + lifespan que arranca el bot Telegram y schedulers async."""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import api, bot, config, db, digest, reminders, web

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("inboxzero")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Validación de config (no bloqueante)
    errors = config.validate()
    for e in errors:
        log.error("CONFIG: %s", e)

    db.init_db()
    log.info("DB inicializada en %s", config.DB_PATH)

    application = None
    background_tasks: list[asyncio.Task] = []
    stop_event = asyncio.Event()

    if config.TELEGRAM_BOT_TOKEN:
        try:
            application = bot.build_application()
            await application.initialize()
            await application.start()
            await application.updater.start_polling(drop_pending_updates=False)
            log.info("Bot de Telegram corriendo en modo polling.")

            # Schedulers
            background_tasks.append(
                asyncio.create_task(reminders.reminder_loop(application.bot, stop_event), name="reminders_loop")
            )
            background_tasks.append(
                asyncio.create_task(digest.digest_loop(application.bot, stop_event), name="digest_loop")
            )
            log.info("Schedulers arrancados (reminders + digest).")

            log.info(
                "Features: LLM=%s, digest=%s, web_ui=%s",
                "on" if config.llm_enabled() else "off",
                "on" if config.DIGEST_ENABLED else "off",
                "on" if config.WEB_UI_ENABLED else "off",
            )
        except Exception:
            log.exception("No pude arrancar el bot.")
            application = None
    else:
        log.warning("Bot NO arrancado: TELEGRAM_BOT_TOKEN vacío.")

    app.state.tg_app = application
    try:
        yield
    finally:
        log.info("Shutdown: deteniendo schedulers...")
        stop_event.set()
        for t in background_tasks:
            try:
                await asyncio.wait_for(t, timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                t.cancel()
        if application is not None:
            log.info("Apagando bot...")
            for stage, fn in (
                ("updater.stop", application.updater.stop),
                ("application.stop", application.stop),
                ("application.shutdown", application.shutdown),
            ):
                try:
                    await fn()
                except Exception:
                    log.exception("Error en %s.", stage)


app = FastAPI(title="InboxZero", lifespan=lifespan)
app.include_router(api.router)
app.include_router(web.router)


@app.get("/healthz")
def healthz() -> dict:
    return {
        "status": "ok",
        "bot_running": getattr(app.state, "tg_app", None) is not None,
        "config_errors": config.validate(),
        "features": {
            "llm": config.llm_enabled(),
            "digest": config.DIGEST_ENABLED,
            "web_ui": config.WEB_UI_ENABLED,
        },
    }


@app.get("/")
def root() -> dict:
    return {
        "service": "inboxzero",
        "version": "v2",
        "endpoints": [
            "/healthz",
            "/pending", "/mark-synced", "/stats",
            "/reminders/unsynced", "/reminders/mark-synced",
            "/ui",
        ],
    }
