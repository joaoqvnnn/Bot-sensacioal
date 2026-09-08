# ============================================
# LARIZINHA STORE - BOT
# Dockerfile multiestágio otimizado
# ============================================

FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .

RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install -r requirements.txt

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app"

RUN groupadd -r botuser && useradd -r -g botuser botuser

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv

COPY --chown=botuser:botuser . .

RUN mkdir -p /app/logs && chown -R botuser:botuser /app/logs

USER botuser

CMD ["python", "-m", "bot"]
