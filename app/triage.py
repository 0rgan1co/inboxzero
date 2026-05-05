"""Heurística de triage: sugiere a qué agente derivar cada captura.

Lee el texto de la captura y propone una de:
  - 'tres-monos'    (priorización, plan diario/semanal, reportes tácticos)
  - 'res-non-verba' (coordinación, decidir quién hace qué, research general)
  - 'colibri'       (crear/mantener perfiles de agentes)
  - None            (requiere decisión del usuario, no auto-derivable)

Sin LLM. Reglas explícitas en orden, primer match gana.
"""
from __future__ import annotations

import re

# Agentes disponibles (alineados con vault/10-agents/)
AGENTS = ("tres-monos", "res-non-verba", "colibri")

# Reglas en orden de prioridad
RULES: list[tuple[str, re.Pattern[str]]] = [
    # colibrí: crear/diseñar agentes nuevos
    ("colibri", re.compile(
        r"\b(crear|disen[ñn]ar|nuevo)\s+agente|agente\s+nuevo|perfil\s+de\s+agente|roster",
        re.IGNORECASE,
    )),
    # tres-monos: priorización, planes, reportes
    ("tres-monos", re.compile(
        r"\b(priorizar|priorizaci[oó]n|plan(ear|ificar)?\s+(d[ií]a|semana)|"
        r"qu[eé]\s+hago\s+hoy|qu[eé]\s+hago\s+ma[nñ]ana|"
        r"foco\s+(de\s+)?(hoy|esta\s+semana)|"
        r"dashboard|reporte|check.?in|standup|hoy\s+(tengo|debo|hay))\b",
        re.IGNORECASE,
    )),
    # res-non-verba: coordinación general, research, "delegar" explícito
    ("res-non-verba", re.compile(
        r"\b(coordin(ar|aci[oó]n)|delegar|deleg(ar|aci[oó]n)|"
        r"research|investigar|buscar\s+info|relevar|"
        r"qui[eé]n\s+(hace|atiende|se\s+encarga))\b",
        re.IGNORECASE,
    )),
]


def suggest_agent(text: str, classification: str) -> str | None:
    """Devuelve el nombre del agente sugerido, o None si requiere decisión humana."""
    if not text:
        return None

    # Recordatorios y notas: por defecto requieren decisión (no son tareas claras).
    # Tareas e ideas: probamos heurística.
    for agent, pattern in RULES:
        if pattern.search(text):
            return agent

    # Tareas con verbo claro al inicio → res-non-verba (orquesta)
    if classification == "tarea":
        first_word = text.strip().split(maxsplit=1)[0].lower() if text.strip() else ""
        action_verbs = {
            "mandar", "enviar", "llamar", "escribir", "responder",
            "leer", "revisar", "preparar", "armar", "subir",
            "publicar", "compartir", "consultar",
        }
        if first_word in action_verbs:
            return "res-non-verba"

    # No matchea: requiere decisión
    return None


def emoji_for_agent(agent: str | None) -> str:
    """Emoji para mostrar en el mensaje de Telegram."""
    return {
        "tres-monos": "🐒",
        "res-non-verba": "🟡",
        "colibri": "🐦",
    }.get(agent or "", "🤔")
