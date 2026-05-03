"""Llamadas opcionales a la API de Claude para clasificación.

Si ANTHROPIC_API_KEY no está, las funciones devuelven None y el caller
hace fallback a heurística.

Implementado con urllib (stdlib) para no agregar dependencia.
"""
import asyncio
import json
import logging
import urllib.error
import urllib.request

from . import config

log = logging.getLogger("inboxzero.llm")

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

CLASSIFY_PROMPT = """\
Sos un clasificador. Recibís UN mensaje breve en español rioplatense y devolvés
EXACTAMENTE una de estas categorías, sin explicación:

- idea     → exploración, hipótesis, brainstorm, "y si...", "tal vez..."
- pedido   → solicitud explícita ("podés...", "ayudame con...", "necesito que...")
- tarea    → algo accionable propio ("tengo que...", "TODO", "recordar X")
- nota     → registro, observación, info que no encaja en lo anterior

Mensaje:
{text}

Respondé SOLO con una palabra: idea | pedido | tarea | nota
"""

VALID = {"idea", "pedido", "tarea", "nota"}


def _call_claude_sync(text: str, timeout: float = 8.0) -> str | None:
    """Llamada bloqueante. Devuelve la categoría o None si falla."""
    if not config.ANTHROPIC_API_KEY:
        return None
    body = {
        "model": config.ANTHROPIC_MODEL,
        "max_tokens": 8,
        "messages": [
            {"role": "user", "content": CLASSIFY_PROMPT.format(text=text[:4000])}
        ],
    }
    req = urllib.request.Request(
        ANTHROPIC_URL,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
    )
    req.add_header("x-api-key", config.ANTHROPIC_API_KEY)
    req.add_header("anthropic-version", ANTHROPIC_VERSION)
    req.add_header("content-type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        # Respuesta tipo: { content: [{type: "text", text: "..."}], ... }
        for block in data.get("content", []):
            if block.get("type") == "text":
                raw = (block.get("text") or "").strip().lower()
                # tomamos solo la primera palabra alfabética
                token = "".join(ch for ch in raw if ch.isalpha())
                if token in VALID:
                    return token
        return None
    except urllib.error.HTTPError as e:
        body_txt = ""
        try:
            body_txt = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        log.warning("Claude API HTTP %s: %s", e.code, body_txt[:200])
        return None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        log.warning("Claude API error: %s", e)
        return None


async def classify_with_claude(text: str) -> str | None:
    """Versión async (corre la llamada bloqueante en thread pool)."""
    return await asyncio.to_thread(_call_claude_sync, text)
