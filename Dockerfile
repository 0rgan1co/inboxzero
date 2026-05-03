# Imagen multi-arch (funciona en x86_64 y ARM64 — Oracle Ampere usa ARM)
FROM python:3.11-slim AS base

# Mejoras de runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Instalar deps primero para aprovechar cache de capa
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copiar código
COPY app/ ./app/

# Crear directorio de datos. El compose lo monta como volumen.
RUN mkdir -p /data
VOLUME ["/data"]

# Healthcheck nativo de Docker (independiente del proxy)
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; \
    urllib.request.urlopen('http://localhost:8000/healthz', timeout=3); sys.exit(0)" || exit 1

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
