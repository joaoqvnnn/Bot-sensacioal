"""
Serviço de pagamentos Pix via Mercado Pago.

Fornece funções para:
- Criar cobrança Pix (QR Code e código copia-e-cola)
- Processar webhook de confirmação do provedor com idempotência
- Confirmar pagamento (PAID) e creditar carteira
- Marcar como expirado/falho/cancelado

Todas as operações financeiras são atômicas e usam idempotência.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.core.config import settings
from bot.models.payment import Payment
from bot.models.user import User
from bot.services.wallet_service import credit_wallet

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Funções auxiliares internas (serão conectadas ao cliente real)
# ----------------------------------------------------------------------

async def _create_pix_charge_via_provider(amount_cents: int, expires_at: datetime) -> dict:
    """
    Cria uma cobrança Pix no provedor (Mercado Pago).

    Esta função deve ser implementada com a API real.
    Por enquanto, levanta NotImplementedError até que a integração
    seja concluída no módulo bot.integrations.mercadopago.

    Args:
        amount_cents: Valor em centavos.
        expires_at: Data de expiração.

    Returns:
        dict: Dados da cobrança (external_payment_id, qr_code_url, pix_code).
    """
    # TODO: Implementar chamada real à API do Mercado Pago.
    raise NotImplementedError("Integração com Mercado Pago ainda não implementada.")


def _get_payment_by_idempotency_key(session, tenant_id, idempotency_key):
    """Busca pagamento existente pela chave de idempotência."""
    stmt = select(Payment).where(
        Payment.tenant_id == tenant_id,
        Payment.idempotency_key == idempotency_key,
        Payment.deleted_at.is_(None),
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


# ----------------------------------------------------------------------
# CRIAÇÃO DE PAGAMENTO
# ----------------------------------------------------------------------

async def create_pix_payment(
    session: AsyncSession,
    tenant_id: UUID,
    user_id: UUID,
    amount_cents: int,
    bonus_cents: int = 0,
    idempotency_key: Optional[str] = None,
) -> Payment:
    """
    Cria um pagamento Pix pendente.

    Se uma chave de idempotência for fornecida e já existir um pagamento
    pendente correspondente, retorna o existente (evita duplicidade).

    Args:
        session: Sessão do banco.
        tenant_id: ID do tenant.
        user_id: ID do usuário.
        amount_cents: Valor da cobrança em centavos.
        bonus_cents: Bônus a ser creditado (se houver).
        idempotency_key: Chave para idempotência.

    Returns:
        Payment: Pagamento criado (ou existente).
    """
    if amount_cents <= 0:
        raise ValueError("Valor do pagamento deve ser positivo.")

    # Se idempotency_key fornecida, verificar se já existe
    if idempotency_key:
        existing = await _get_payment_by_idempotency_key(session, tenant_id, idempotency_key)
        if existing and existing.status == "PENDING":
            logger.info("Pagamento pendente já existe para idempotency_key, retornando existente.")
            return existing

    # Define expiração conforme configuração (padrão 10 minutos)
    expiration_minutes = settings.MERCADO_PAGO_EXPIRATION_MINUTES
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=expiration_minutes)

    # Cria registro inicial PENDING
    payment = Payment(
        tenant_id=tenant_id,
        user_id=user_id,
        status="PENDING",
        amount_cents=amount_cents,
        bonus_cents=bonus_cents,
        idempotency_key=idempotency_key,
        expires_at=expires_at,
    )
    session.add(payment)
    await session.flush()  # obtém ID

    # Tenta criar cobrança no provedor
    try:
        provider_data = await _create_pix_charge_via_provider(amount_cents, expires_at)
        payment.external_payment_id = provider_data.get("external_payment_id")
        payment.qr_code_url = provider_data.get("qr_code_url")
        payment.pix_code = provider_data.get("pix_code")
    except NotImplementedError:
        # Marcar como FAILED? Não; manter PENDING para depois integrar.
        # Em produção, isso não deve ocorrer.
        logger.warning("Cliente Mercado Pago não implementado; pagamento permanece PENDING sem dados do provedor.")

    await session.commit()
    await session.refresh(payment)
    logger.info(f"Pagamento criado: id={payment.id}, amount={amount_cents}, user_id={user_id}")
    return payment


# ----------------------------------------------------------------------
# PROCESSAMENTO DE WEBHOOK
# ----------------------------------------------------------------------

async def process_payment_webhook(
    session: AsyncSession,
    tenant_id: UUID,
    payment_id: UUID,
    external_status: str,
    provider_response: Optional[str] = None,
) -> Payment:
    """
    Processa a notificação do provedor sobre o status de um pagamento.

    Args:
        session: Sessão do banco.
        tenant_id: ID do tenant.
        payment_id: ID interno do pagamento.
        external_status: Status informado pelo provedor (approved, pending, expired, etc.)
        provider_response: Resposta bruta do webhook (para auditoria).

    Returns:
        Payment: Pagamento atualizado.
    """
    stmt = select(Payment).where(
        Payment.tenant_id == tenant_id,
        Payment.id == payment_id,
        Payment.deleted_at.is_(None),
    )
    result = await session.execute(stmt)
    payment = result.scalar_one_or_none()

    if payment is None:
        raise ValueError("Pagamento não encontrado.")

    if provider_response:
        payment.provider_response = provider_response

    # Mapeia status do provedor para status interno
    status_map = {
        "approved": "PAID",
        "pending": "PENDING",
        "in_process": "PENDING",
        "expired": "EXPIRED",
        "cancelled": "CANCELLED",
        "failed": "FAILED",
        "rejected": "FAILED",
    }
    new_status = status_map.get(external_status.lower(), payment.status)

    if new_status == "PAID" and payment.status != "PAID":
        # Confirmação: credita carteira e marca pago
        await _mark_payment_as_paid(session, payment)
    elif new_status != payment.status:
        payment.status = new_status
        if new_status == "EXPIRED":
            payment.expires_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(payment)

    logger.info(f"Webhook processado para payment_id={payment.id}, status={payment.status}")
    return payment


async def _mark_payment_as_paid(session: AsyncSession, payment: Payment) -> None:
    """
    Marca o pagamento como PAID e credita a carteira do usuário.

    Usa idempotência: se já estiver PAID, não faz nada.
    """
    if payment.status == "PAID":
        logger.info(f"Payment {payment.id} já está PAID, ignorando.")
        return

    # Credita valor na carteira
    await credit_wallet(
        session,
        tenant_id=payment.tenant_id,
        user_id=payment.user_id,
        amount_cents=int(payment.amount_cents),
        entry_type="deposit",
        description="Recarga via Pix",
        reference_id=payment.id,
    )

    # Se houver bônus, credita também
    if payment.bonus_cents and payment.bonus_cents > 0:
        await credit_wallet(
            session,
            tenant_id=payment.tenant_id,
            user_id=payment.user_id,
            amount_cents=int(payment.bonus_cents),
            entry_type="bonus",
            description="Bônus de recarga",
            reference_id=payment.id,
        )

    payment.status = "PAID"
    payment.paid_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(payment)

    logger.info(f"Pagamento {payment.id} confirmado. Carteira creditada para user_id={payment.user_id}.")


# ----------------------------------------------------------------------
# CONSULTAS
# ----------------------------------------------------------------------

async def get_payment_by_id(
    session: AsyncSession,
    tenant_id: UUID,
    payment_id: UUID,
) -> Optional[Payment]:
    """
    Obtém um pagamento pelo ID.

    Args:
        session: Sessão do banco.
        tenant_id: ID do tenant.
        payment_id: ID do pagamento.

    Returns:
        Optional[Payment]: Pagamento ou None.
    """
    stmt = select(Payment).where(
        Payment.tenant_id == tenant_id,
        Payment.id == payment_id,
        Payment.deleted_at.is_(None),
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()
