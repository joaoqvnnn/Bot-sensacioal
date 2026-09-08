# ============================================
# LARIZINHA STORE - BOT + WEBHOOK
# Dockerfile multiestágio otimizado
# ============================================

# ---------- ESTÁGIO 1: Builder ----------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Copia requirements e instala em virtualenv
COPY requirements.txt .

RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install -r requirements.txt

# ---------- ESTÁGIO 2: Runtime ----------
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app"

# Cria usuário não-root
RUN groupadd -r botuser && useradd -r -g botuser botuser

WORKDIR /app

# Copia virtualenv do builder
COPY --from=builder /opt/venv /opt/venv

# Copia código
COPY --chown=botuser:botuser . .

# Cria diretório de logs
RUN mkdir -p /app/logs && chown -R botuser:botuser /app/logs

USER botuser

# Porta para o webhook_server
EXPOSE 8000

# Comando final: inicia o servidor webhook (que também roda o bot)
CMD ["python", "-m", "bot.webhook_server"]
