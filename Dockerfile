# Imagen multi-arch (funciona en x86_64 y ARM64 — Apple Silicon y Oracle Ampere)
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ffmpeg = decoder de audio para Whisper
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

# Instalar torch CPU-only ANTES del resto. Es mucho más liviano que torch completo
# (no instala CUDA). openai-whisper detecta el torch existente y no lo reinstala.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

RUN pip install -r requirements.txt

# Pre-descargar el modelo Whisper para que el primer arranque sea rápido.
# Configurable en build-time: --build-arg WHISPER_MODEL=small
ARG WHISPER_MODEL=base
ENV WHISPER_MODEL=${WHISPER_MODEL}
RUN python -c "import whisper; whisper.load_model('${WHISPER_MODEL}')" || \
    echo "WARNING: no se pudo precargar el modelo (se bajará al primer uso)"

COPY app/ ./app/

RUN mkdir -p /data
VOLUME ["/data"]

# start-period ampliado a 60s porque cargar Whisper al startup tarda ~5-15s
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request,sys; \
    urllib.request.urlopen('http://localhost:8000/healthz', timeout=3); sys.exit(0)" || exit 1

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
