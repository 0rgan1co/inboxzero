"""Carga y valida configuración desde variables de entorno."""
import os
from dotenv import load_dotenv

load_dotenv()


def _parse_user_ids(raw: str) -> set[int]:
    if not raw:
        return set()
    out = set()
    for piece in raw.split(","):
        piece = piece.strip()
        if not piece:
            continue
        try:
            out.add(int(piece))
        except ValueError:
            pass
    return out


def _bool(raw: str | None, default: bool = False) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on", "si", "sí")


def _int(raw: str | None, default: int) -> int:
    if not raw:
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


# --- v1 ---
TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED_USER_IDS: set[int] = _parse_user_ids(os.environ.get("ALLOWED_USER_IDS", ""))
SYNC_API_KEY: str = os.environ.get("SYNC_API_KEY", "").strip()
DB_PATH: str = os.environ.get("DB_PATH", "./inboxzero.db")
PORT: int = _int(os.environ.get("PORT"), 8000)

# --- v2 ---
ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL: str = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001").strip()

DIGEST_ENABLED: bool = _bool(os.environ.get("DIGEST_ENABLED"), default=False)
DIGEST_HOUR: int = _int(os.environ.get("DIGEST_HOUR"), 8)
DIGEST_MINUTE: int = _int(os.environ.get("DIGEST_MINUTE"), 0)
DIGEST_TZ: str = os.environ.get("DIGEST_TZ", "America/Argentina/Buenos_Aires").strip()
DIGEST_CHAT_ID: int = _int(os.environ.get("DIGEST_CHAT_ID"), 0)

WEB_UI_ENABLED: bool = _bool(os.environ.get("WEB_UI_ENABLED"), default=True)


def validate() -> list[str]:
    errors: list[str] = []
    if not TELEGRAM_BOT_TOKEN:
        errors.append("TELEGRAM_BOT_TOKEN no está seteado.")
    if not SYNC_API_KEY or SYNC_API_KEY == "cambiar-por-token-largo-aleatorio":
        errors.append("SYNC_API_KEY no está seteado o usa el valor por defecto. Generá uno con `openssl rand -hex 32`.")
    if not ALLOWED_USER_IDS:
        errors.append(
            "ALLOWED_USER_IDS está vacío. El bot rechazará TODOS los mensajes hasta que pongas tu user_id."
        )
    if DIGEST_ENABLED and DIGEST_CHAT_ID == 0:
        errors.append("DIGEST_ENABLED=true pero DIGEST_CHAT_ID no está seteado. Sin chat al cual mandar el digest.")
    return errors


def llm_enabled() -> bool:
    return bool(ANTHROPIC_API_KEY)
