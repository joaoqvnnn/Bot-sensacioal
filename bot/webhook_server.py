"""
Servidor HTTP para receber webhooks do Mercado Pago enquanto roda o bot.
Inclui validação de assinatura HMAC, criação automática das tabelas no banco,
e seed de tenant/admin para testes.
"""

import asyncio
import hashlib
import hmac
import logging
import threading
import uvicorn

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from fastapi import FastAPI, Request, HTTPException

from bot.core.config import settings
from bot.core.database import get_async_engine, get_async_session_factory, Base
from bot.handlers import register_all_handlers
from bot.services.payment_service import process_payment_webhook
from bot.core.logging import setup_logging
from bot.core.redis import create_redis_client, close_redis_client

# Importa todos os modelos para registrar na metadata
import bot.models  # noqa: F401

logger = logging.getLogger(__name__)

app = FastAPI()


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/webhook/mercadopago")
async def mercado_pago_webhook(request: Request):
    """Recebe notificações do Mercado Pago e processa o pagamento."""
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

    async with get_async_session_factory()() as session:
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


async def setup_database():
    """Cria as tabelas no banco e insere tenant/admin se necessário."""
    engine = get_async_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Cria um tenant se não existir
    from sqlalchemy import select
    from bot.models.tenant import Tenant
    from bot.models.user import User
    from datetime import datetime, timezone

    async with get_async_session_factory()() as session:
        tenant = (await session.execute(
            select(Tenant).where(Tenant.slug == "loja_teste")
        )).scalar_one_or_none()

        if not tenant:
            tenant = Tenant(
                name="Loja Teste",
                slug="loja_teste",
                plan="basic",
                is_active=True,
            )
            session.add(tenant)
            await session.commit()

        # Cria admin se não existir
        owner_id = settings.TELEGRAM_OWNER_ID
        if owner_id:
            user = (await session.execute(
                select(User).where(
                    User.tenant_id == tenant.id,
                    User.telegram_id == owner_id,
                )
            )).scalar_one_or_none()

            if not user:
                user = User(
                    tenant_id=tenant.id,
                    telegram_id=owner_id,
                    is_owner=True,
                    is_admin=True,
                    registered_at=datetime.now(timezone.utc),
                )
                session.add(user)
                await session.commit()


async def start_bot():
    """Inicia o bot em polling."""
    print("🚀 Iniciando bot...")
    setup_logging(
        level=settings.LOG_LEVEL,
        app_name=settings.APP_NAME,
        env=settings.APP_ENV,
    )

    print("🗄️ Configurando banco de dados...")
    await setup_database()

    print("📡 Conectando ao Telegram...")
    redis_client = await create_redis_client(settings)
    storage = MemoryStorage()

    bot = Bot(
        token=settings.TELEGRAM_BOT_TOKEN.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=storage)

    register_all_handlers(dp)

    # Apaga webhook ativo para permitir polling
    await bot.delete_webhook(drop_pending_updates=True)

    print("✅ Bot conectado e polling iniciado")
    await dp.start_polling(bot)
    await bot.session.close()
    await close_redis_client(redis_client)


if __name__ == "__main__":
    def run_server():
        uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    asyncio.run(start_bot())
