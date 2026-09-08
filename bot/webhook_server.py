"""
Servidor HTTP para receber webhooks do Mercado Pago enquanto roda o bot.
Inclui validação de assinatura HMAC e inicia o bot em thread separada.
"""

import asyncio
import hashlib
import hmac
import logging
import threading
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from fastapi import FastAPI, Request, HTTPException
import uvicorn

from bot.core.config import settings
from bot.core.database import get_async_session_factory
from bot.handlers import register_all_handlers
from bot.services.payment_service import process_payment_webhook
from bot.core.logging import setup_logging
from bot.core.redis import create_redis_client, close_redis_client

logger = logging.getLogger(__name__)

app = FastAPI()


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/webhook/mercadopago")
async def mercado_pago_webhook(request: Request):
    """Recebe notificações do Mercado Pago e processa o pagamento."""
    # Valida assinatura
    secret = settings.MERCADO_PAGO_WEBHOOK_SECRET.get_secret_value() if settings.MERCADO_PAGO_WEBHOOK_SECRET else None

    if secret:
        request_id = request.headers.get("x-request-id", "")
        signature = request.headers.get("x-signature", "")
        if not request_id or not signature:
            raise HTTPException(status_code=400, detail="Headers ausentes")

        expected = hmac.new(
            secret.encode("utf-8"),
            request_id.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(expected, signature):
            raise HTTPException(status_code=403, detail="Assinatura inválida")

    payload = await request.json()
    action = payload.get("action", "")
    data = payload.get("data", {})

    payment_id = data.get("id")
    if not payment_id:
        return {"status": "ignored"}

    status_map = {
        "payment.created": "pending",
        "payment.updated": "approved",
        "payment.approved": "approved",
        "payment.failed": "failed",
        "payment.rejected": "failed",
        "payment.cancelled": "cancelled",
    }
    external_status = status_map.get(action, "pending")

    from sqlalchemy import select
    from bot.models.tenant import Tenant
    from bot.models.payment import Payment

    async with get_async_session_factory() as session:
        payment = (await session.execute(
            select(Payment).where(Payment.external_payment_id == str(payment_id))
        )).scalar_one_or_none()

        if not payment:
            return {"status": "payment_not_found"}

        tenant = (await session.execute(
            select(Tenant).where(Tenant.id == payment.tenant_id)
        )).scalar_one_or_none()

        if not tenant:
            return {"status": "tenant_not_found"}

        await process_payment_webhook(
            session=session,
            tenant_id=tenant.id,
            payment_id=payment.id,
            external_status=external_status,
        )

    return {"status": "processed"}


async def start_bot():
    """Inicia o bot em polling."""
    setup_logging(
        level=settings.LOG_LEVEL,
        app_name=settings.APP_NAME,
        env=settings.APP_ENV,
    )

    redis_client = await create_redis_client(settings)
    storage = MemoryStorage()

    bot = Bot(
        token=settings.TELEGRAM_BOT_TOKEN.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=storage)

    register_all_handlers(dp)

    await dp.start_polling(bot)
    await bot.session.close()
    await close_redis_client(redis_client)


if __name__ == "__main__":
    # Inicia o bot em uma thread separada
    bot_thread = threading.Thread(target=lambda: asyncio.run(start_bot()), daemon=True)
    bot_thread.start()

    # Inicia o servidor HTTP
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
