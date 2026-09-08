"""
Serviço de entrega de produtos.

Após a compra, cria jobs de entrega e tokens de acesso para ativação.
Métodos:
- create_delivery_job: cria DeliveryJob pendente (Telegram, WhatsApp, e-mail)
- generate_product_access_token: gera token único com hash e expiração

Tudo com transações e idempotência.
"""

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.delivery import DeliveryJob
from bot.models.order import Order, OrderItem
from bot.models.product_access_token import ProductAccessToken
from bot.models.user import User
from bot.models.tenant import Tenant

logger = logging.getLogger(__name__)


async def create_delivery_job(
    session: AsyncSession,
    tenant_id: UUID,
    order_id: UUID,
    user_id: UUID,
    method: str,
    idempotency_key: Optional[str] = None,
) -> DeliveryJob:
    """
    Cria um job de entrega pendente para um pedido.

    Args:
        session: Sessão do banco.
        tenant_id: ID do tenant.
        order_id: ID do pedido.
        user_id: ID do usuário.
        method: Método de entrega (TELEGRAM, WHATSAPP, EMAIL).
        idempotency_key: Chave de idempotência opcional.

    Returns:
        DeliveryJob: Job criado ou existente (se idempotência).
    """
    if method not in ("TELEGRAM", "WHATSAPP", "EMAIL"):
        raise ValueError("Método de entrega inválido.")

    # Verifica idempotência
    if idempotency_key:
        stmt = select(DeliveryJob).where(
            DeliveryJob.tenant_id == tenant_id,
            DeliveryJob.idempotency_key == idempotency_key,
            DeliveryJob.deleted_at.is_(None),
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing:
            logger.info("DeliveryJob já existente para idempotency_key, retornando existente.")
            return existing

    job = DeliveryJob(
        tenant_id=tenant_id,
        order_id=order_id,
        user_id=user_id,
        method=method,
        status="PENDING",
        idempotency_key=idempotency_key,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    logger.info(f"DeliveryJob criado: id={job.id}, method={method}, order_id={order_id}")
    return job


async def generate_product_access_token(
    session: AsyncSession,
    tenant_id: UUID,
    user_id: UUID,
    order_id: UUID,
    order_item_id: Optional[UUID] = None,
    expires_hours: int = 24,
) -> ProductAccessToken:
    """
    Gera um token de acesso único para ativação/consulta de produto.

    O token é gerado com `secrets.token_urlsafe`, e apenas o hash SHA-256
    é armazenado. Expira após `expires_hours`.

    Args:
        session: Sessão do banco.
        tenant_id: ID do tenant.
        user_id: ID do usuário.
        order_id: ID do pedido.
        order_item_id: ID do item do pedido (opcional).
        expires_hours: Validade do token em horas.

    Returns:
        ProductAccessToken: Token criado (com código puro armazenado temporariamente em `_plain_token`).
    """
    # Gera token puro
    plain_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(plain_token.encode("utf-8")).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=expires_hours)

    token = ProductAccessToken(
        tenant_id=tenant_id,
        user_id=user_id,
        order_id=order_id,
        order_item_id=order_item_id,
        token_hash=token_hash,
        status="ACTIVE",
        expires_at=expires_at,
    )
    session.add(token)
    await session.commit()
    await session.refresh(token)

    # Mantém o token puro apenas em memória para devolução
    token._plain_token = plain_token
    logger.info(f"ProductAccessToken criado: id={token.id}, order_id={order_id}, expira em {expires_at}")
    return token


async def create_delivery_for_order(
    session: AsyncSession,
    tenant_id: UUID,
    order: Order,
    user: User,
    method: str = "TELEGRAM",
) -> dict:
    """
    Cria job de entrega e token de acesso para um pedido concluído.

    Essa função orquestra a pós-compra: gera token e job de entrega.

    Args:
        session: Sessão do banco.
        tenant_id: ID do tenant.
        order: Instância do pedido.
        user: Instância do usuário.
        method: Método de entrega padrão.

    Returns:
        dict: Dados do job e token (se aplicável).
    """
    # Cria job de entrega
    idempotency_key = f"delivery:{order.id}:{method}"
    job = await create_delivery_job(
        session,
        tenant_id=tenant_id,
        order_id=order.id,
        user_id=user.id,
        method=method,
        idempotency_key=idempotency_key,
    )

    # Gera token de acesso para ativação
    # Usamos o primeiro item do pedido como referência (ou None)
    first_item = (await session.execute(
        select(OrderItem).where(OrderItem.order_id == order.id).limit(1)
    )).scalar_one_or_none()
    token = await generate_product_access_token(
        session,
        tenant_id=tenant_id,
        user_id=user.id,
        order_id=order.id,
        order_item_id=first_item.id if first_item else None,
        expires_hours=24,
    )

    return {
        "delivery_job_id": job.id,
        "method": method,
        "product_access_token": getattr(token, "_plain_token", None),
        "token_expires_at": token.expires_at,
    }
