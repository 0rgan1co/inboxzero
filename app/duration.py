"""Parser de duraciones en español: 'en 2h', 'en 30m', 'en 3 días', 'mañana 9am', etc.

Devuelve datetime UTC. Para resolver 'mañana' usa la zona horaria configurada en
DIGEST_TZ (que también sirve como TZ default del usuario).
"""
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import config

UNIT_TO_SECONDS = {
    "s": 1, "seg": 1, "segs": 1, "segundo": 1, "segundos": 1,
    "m": 60, "min": 60, "mins": 60, "minuto": 60, "minutos": 60,
    "h": 3600, "hr": 3600, "hrs": 3600, "hora": 3600, "horas": 3600,
    "d": 86400, "día": 86400, "dia": 86400, "días": 86400, "dias": 86400,
    "sem": 604800, "semana": 604800, "semanas": 604800,
}

# 'en 2h', 'en 30 min', 'en 3 días'
RX_EN = re.compile(r"^\s*en\s+(\d+)\s*(\w+)", re.IGNORECASE)

# '2h', '30m', '3d'
RX_COMPACT = re.compile(r"^\s*(\d+)\s*(\w+)\s*$", re.IGNORECASE)

# 'mañana 9am', 'mañana 14:30', 'manana 9'
RX_MANANA = re.compile(r"^\s*ma[nñ]ana(?:\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?)?", re.IGNORECASE)

# 'hoy 18:00', 'hoy 6pm'
RX_HOY = re.compile(r"^\s*hoy\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", re.IGNORECASE)


class DurationParseError(ValueError):
    pass


def _user_now() -> datetime:
    return datetime.now(ZoneInfo(config.DIGEST_TZ))


def _to_24h(hour: int, ampm: str | None) -> int:
    if ampm is None:
        return hour
    a = ampm.lower()
    if a == "am":
        return 0 if hour == 12 else hour
    if a == "pm":
        return 12 if hour == 12 else hour + 12
    return hour


def parse_duration(text: str) -> tuple[datetime, str]:
    """
    Devuelve (datetime UTC del fire, texto del recordatorio).
    Levanta DurationParseError si no puede parsear.

    Reglas (orden):
      1. 'en N <unidad> <texto>'  → fire = ahora + N <unidad>
      2. '<N><unidad> <texto>'    → idem
      3. 'mañana[ HH[:MM][am|pm]] <texto>' → mañana a esa hora (default 9am)
      4. 'hoy HH[:MM][am|pm] <texto>'      → hoy a esa hora
    """
    t = text.strip()

    # 1 & 2 — unidades relativas
    for rx in (RX_EN, None):
        if rx is RX_EN:
            m = rx.match(t)
        else:
            m = RX_COMPACT.match(t.split(maxsplit=1)[0]) if t else None
            if not m and " " in t:
                # rx compacto: primer token completo
                first = t.split(maxsplit=1)[0]
                m = RX_COMPACT.match(first)
        if m:
            n = int(m.group(1))
            unit = m.group(2).lower()
            if unit not in UNIT_TO_SECONDS:
                continue
            secs = n * UNIT_TO_SECONDS[unit]
            if secs <= 0:
                raise DurationParseError("La duración tiene que ser positiva.")
            fire_local = _user_now() + timedelta(seconds=secs)
            # Texto: lo que sigue después del match
            rest = t[m.end():].strip()
            if rest.startswith(",") or rest.startswith(":"):
                rest = rest[1:].strip()
            return (fire_local.astimezone(timezone.utc), rest or "(sin texto)")

    # 3 — mañana
    m = RX_MANANA.match(t)
    if m:
        h = int(m.group(1)) if m.group(1) else 9
        mi = int(m.group(2)) if m.group(2) else 0
        ampm = m.group(3)
        h = _to_24h(h, ampm)
        if not (0 <= h <= 23 and 0 <= mi <= 59):
            raise DurationParseError("Hora inválida.")
        now = _user_now()
        target_local = (now + timedelta(days=1)).replace(hour=h, minute=mi, second=0, microsecond=0)
        rest = t[m.end():].strip()
        return (target_local.astimezone(timezone.utc), rest or "(sin texto)")

    # 4 — hoy HH...
    m = RX_HOY.match(t)
    if m:
        h = int(m.group(1))
        mi = int(m.group(2)) if m.group(2) else 0
        ampm = m.group(3)
        h = _to_24h(h, ampm)
        if not (0 <= h <= 23 and 0 <= mi <= 59):
            raise DurationParseError("Hora inválida.")
        now = _user_now()
        target_local = now.replace(hour=h, minute=mi, second=0, microsecond=0)
        if target_local <= now:
            raise DurationParseError("Esa hora de hoy ya pasó. Usá 'mañana ...' o un offset relativo.")
        rest = t[m.end():].strip()
        return (target_local.astimezone(timezone.utc), rest or "(sin texto)")

    raise DurationParseError(
        "No entendí la duración. Probá: 'en 2h hablar con X', '30m revisar email', "
        "'mañana 9am llamar al banco', 'hoy 18:00 cerrar laptop'."
    )


def format_local(dt_utc_iso: str) -> str:
    """Convierte ISO UTC a hora local del usuario, formateada para humanos."""
    try:
        dt = datetime.fromisoformat(dt_utc_iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone(ZoneInfo(config.DIGEST_TZ))
        return local.strftime("%a %d/%m %H:%M")
    except Exception:
        return dt_utc_iso
