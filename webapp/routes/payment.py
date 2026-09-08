"""
Rotas de pagamento Pix para o Telegram Mini App.

Endpoints:
- POST /api/payment/create
- GET  /api/payment/{payment_id}/status
- POST /api/payment/{payment_id}/copy

Usa MercadoPagoClient e payment_service reais.
"""

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from bot.core.database import get_async_session_factory
from bot.core.utils import cents_to_brl
from bot.models.payment import Payment
from bot.models.user import User
from bot.models.tenant import Tenant
from bot.services.payment_service import create_pix_payment, get_payment_by_id
from bot.integrations.mercadopago import MercadoPagoClient, MercadoPagoError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/payment", tags=["payment"])


class PaymentCreateRequest(BaseModel):
    user_id: UUID
    amount_cents: int
    idempotency_key: Optional[str] = None


class PaymentStatusResponse(BaseModel):
    payment_id: UUID
    status: str
    amount_cents: int
    amount_brl: str
    pix_code: Optional[str] = None
    qr_code_url: Optional[str] = None


async def _get_tenant_from_header(bot_username: Optional[str] = Header(None)):
    """Obtém tenant pelo username do bot ou primeiro ativo."""
    from sqlalchemy import select
    from bot.services.user_service import get_tenant_for_bot

    async with get_async_session_factory() as session:
        if bot_username:
            tenant = await get_tenant_for_bot(session, bot_username)
            if tenant:
                return tenant
        stmt = select(Tenant).where(
            Tenant.is_active == True,
            Tenant.deleted_at.is_(None),
        ).order_by(Tenant.created_at.asc())
        result = await session.execute(stmt)
        return result.scalars().first()


@router.post("/create", response_model=PaymentStatusResponse)
async def create_payment(request: PaymentCreateRequest, bot_username: Optional[str] = Header(None)):
    """
    Cria um pagamento Pix.

    Args:
        request: Dados do usuário, valor e chave de idempotência.
        bot_username: Username do bot.

    Returns:
        PaymentStatusResponse: Dados do pagamento criado.
    """
    tenant = await _get_tenant_from_header(bot_username)
    if tenant is None:
        raise HTTPException(status_code=503, detail="Sistema indisponível.")

    async with get_async_session_factory() as session:
        user = (await session.execute(
            select(User).where(User.id == request.user_id, User.tenant_id == tenant.id)
        )).scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=404, detail="Usuário não encontrado.")

        try:
            payment = await create_pix_payment(
                session=session,
                tenant_id=tenant.id,
                user_id=user.id,
                amount_cents=request.amount_cents,
                bonus_cents=0,
                idempotency_key=request.idempotency_key,
            )
        except MercadoPagoError as e:
            logger.error(f"Erro ao criar pagamento: {e}")
            raise HTTPException(status_code=502, detail="Falha na comunicação com Mercado Pago.")
        except Exception as e:
            logger.exception(f"Erro interno: {e}")
            raise HTTPException(status_code=500, detail="Erro interno.")

        return PaymentStatusResponse(
            payment_id=payment.id,
            status=payment.status,
            amount_cents=int(payment.amount_cents),
            amount_brl=cents_to_brl(int(payment.amount_cents)),
            pix_code=payment.pix_code,
            qr_code_url=payment.qr_code_url,
        )


@router.get("/{payment_id}/status", response_model=PaymentStatusResponse)
async def get_payment_status(payment_id: UUID, bot_username: Optional[str] = Header(None)):
    """
    Consulta o status de um pagamento.

    Args:
        payment_id: ID do pagamento.
        bot_username: Username do bot.

    Returns:
        PaymentStatusResponse: Status atual do pagamento.
    """
    tenant = await _get_tenant_from_header(bot_username)
    if tenant is None:
        raise HTTPException(status_code=503, detail="Sistema indisponível.")

    async with get_async_session_factory() as session:
        payment = await get_payment_by_id(session, tenant.id, payment_id)
        if payment is None:
            raise HTTPException(status_code=404, detail="Pagamento não encontrado.")

        return PaymentStatusResponse(
            payment_id=payment.id,
            status=payment.status,
            amount_cents=int(payment.amount_cents),
            amount_brl=cents_to_brl(int(payment.amount_cents)),
            pix_code=payment.pix_code,
            qr_code_url=payment.qr_code_url,
        )


@router.post("/{payment_id}/copy")
async def copy_pix_code(payment_id: UUID, bot_username: Optional[str] = Header(None)):
    """
    Retorna o código Pix copia-e-cola para o usuário copiar.

    Args:
        payment_id: ID do pagamento.
        bot_username: Username do bot.

    Returns:
        dict: Código Pix.
    """
    tenant = await _get_tenant_from_header(bot_username)
    if tenant is None:
        raise HTTPException(status_code=503, detail="Sistema indisponível.")

    async with get_async_session_factory() as session:
        payment = await get_payment_by_id(session, tenant.id, payment_id)
        if payment is None:
            raise HTTPException(status_code=404, detail="Pagamento não encontrado.")

        if not payment.pix_code:
            raise HTTPException(status_code=400, detail="Código Pix não disponível.")

        return {"pix_code": payment.pix_code}
