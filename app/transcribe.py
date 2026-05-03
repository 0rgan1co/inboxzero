"""Transcripción local de audio con Whisper.

Sin API externa. El modelo se carga UNA vez al startup y queda en memoria.
Las transcripciones corren en thread pool para no bloquear el event loop.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from . import config

log = logging.getLogger("inboxzero.transcribe")

_model = None  # singleton, cargado por load_model() al startup


def load_model() -> bool:
    """Carga el modelo Whisper en memoria. Lento — hacer al startup.

    Devuelve True si quedó listo, False si está deshabilitado o falló.
    """
    global _model
    if not config.WHISPER_ENABLED:
        log.info("Whisper deshabilitado (WHISPER_ENABLED=false).")
        return False
    try:
        import whisper  # import lazy: si la lib no está, no rompe el resto del bot
        log.info("Cargando modelo Whisper '%s'...", config.WHISPER_MODEL)
        _model = whisper.load_model(config.WHISPER_MODEL)
        log.info("Modelo Whisper '%s' cargado y listo.", config.WHISPER_MODEL)
        return True
    except ImportError:
        log.error("openai-whisper no está instalado. Instalar 'openai-whisper' en requirements.")
        return False
    except Exception:
        log.exception("Falló la carga del modelo Whisper.")
        return False


def is_ready() -> bool:
    return _model is not None


def _transcribe_sync(audio_path: str) -> str:
    """Bloqueante: transcribe el archivo y devuelve el texto."""
    if _model is None:
        raise RuntimeError("Whisper no está cargado.")
    lang = config.WHISPER_LANGUAGE.strip() or None
    result = _model.transcribe(
        audio_path,
        language=lang,
        fp16=False,         # CPU
        verbose=False,
    )
    return (result.get("text") or "").strip()


async def transcribe(audio_path: str) -> str:
    """Async wrapper: corre la transcripción en thread pool."""
    return await asyncio.to_thread(_transcribe_sync, audio_path)
