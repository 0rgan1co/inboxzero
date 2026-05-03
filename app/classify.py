"""Clasificación de mensajes.

Cascada:
  1. Comando explícito /idea, /pedido, /tarea, /nota → respeta.
  2. Si LLM disponible (ANTHROPIC_API_KEY seteada) → Claude haiku.
  3. Heurística por keywords.
  4. Default: 'nota'.
"""
import re

from . import config, llm

CATEGORIES = ("idea", "pedido", "tarea", "nota")

HEURISTICS: list[tuple[str, re.Pattern[str]]] = [
    ("pedido", re.compile(r"\b(pod[ée]s|podr[íi]as|me ayud[áa]s|necesito que|por favor)\b", re.IGNORECASE)),
    ("tarea", re.compile(r"\b(todo|tengo que|hay que|debo|pendiente|recordar|recordarme)\b", re.IGNORECASE)),
    ("idea", re.compile(r"\b(idea|y si|qu[ée] tal si|tal vez|brainstorm|hip[oó]tesis|me imagin[oé])\b", re.IGNORECASE)),
]


def _command_category(text: str) -> tuple[str | None, str]:
    """Si el mensaje empieza con /<categoria>, devuelve (cat, resto). Si no, (None, text)."""
    if not text.startswith("/"):
        return None, text
    head, _, rest = text.partition(" ")
    cmd = head.lower().lstrip("/").split("@")[0]
    if cmd in CATEGORIES:
        return cmd, rest.strip() or "(sin texto)"
    return None, text


def _heuristic(text: str) -> str:
    for category, pattern in HEURISTICS:
        if pattern.search(text):
            return category
    return "nota"


def classify(text: str) -> tuple[str, str]:
    """Versión SÍNCRONA (sin LLM). Conservada para tests y fallback puro."""
    t = text.strip()
    cmd_cat, rest = _command_category(t)
    if cmd_cat:
        return cmd_cat, rest
    return _heuristic(t), t


async def classify_async(text: str) -> tuple[str, str]:
    """Versión ASYNC. Si LLM está habilitado, intenta con Claude antes de heurística."""
    t = text.strip()
    cmd_cat, rest = _command_category(t)
    if cmd_cat:
        return cmd_cat, rest

    if config.llm_enabled():
        cat = await llm.classify_with_claude(t)
        if cat in CATEGORIES:
            return cat, t

    return _heuristic(t), t
