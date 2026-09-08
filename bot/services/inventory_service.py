"""
Serviço de controle de estoque.

Gerencia os itens de estoque (InventoryItem) de um produto, aplicando
estados AVAILABLE, RESERVED e SOLD com transações atômicas e locks,
garantindo que duas pessoas não comprem o mesmo item.

A configuração de tempo de reserva é lida da tabela Settings,
permitindo alteração em tempo real pelo painel administrativo.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.inventory_item import InventoryItem
from bot.models.product import Product
from bot.models.settings import Settings

logger = logging.getLogger(__name__)


async def _get_setting(session, tenant_id: UUID, key: str, default: str) -> str:
    """Busca configuração do tenant, com fallback."""
    if tenant_id is None:
        return default
    stmt = select(Settings).where(
        Settings.tenant_id == tenant_id,
        Settings.key == key,
        Settings.deleted_at.is_(None),
    )
    result = await session.execute(stmt)
    setting = result.scalar_one_or_none()
    return setting.value if setting else default


async def get_available_count(
    session: AsyncSession,
    tenant_id: UUID,
    product_id: UUID,
) -> int:
    """
    Retorna a quantidade de itens AVAILABLE de um produto.
    """
    stmt = (
        select(InventoryItem)
        .where(
            InventoryItem.tenant_id == tenant_id,
            InventoryItem.product_id == product_id,
            InventoryItem.status == "AVAILABLE",
            InventoryItem.deleted_at.is_(None),
        )
    )
    result = await session.execute(stmt)
    return len(result.scalars().all())


async def reserve_items(
    session: AsyncSession,
    tenant_id: UUID,
    product_id: UUID,
    user_id: UUID,
    quantity: int = 1,
    reservation_minutes: Optional[int] = None,
) -> List[InventoryItem]:
    """
    Reserva uma quantidade de itens AVAILABLE para um usuário.

    Se `reservation_minutes` for None, lê o valor de Settings
    (chave "reservation_minutes") ou usa 10 como padrão.

    Usa lock (SELECT ... FOR UPDATE) para evitar corrida e overselling.
    """
    if reservation_minutes is None:
        # Lê configuração do banco
        value = await _get_setting(session, tenant_id, "reservation_minutes", "10")
        try:
            reservation_minutes = int(value)
        except ValueError:
            reservation_minutes = 10

    stmt = (
        select(InventoryItem)
        .where(
            InventoryItem.tenant_id == tenant_id,
            InventoryItem.product_id == product_id,
            InventoryItem.status == "AVAILABLE",
            InventoryItem.deleted_at.is_(None),
        )
        .order_by(InventoryItem.created_at.asc())
        .limit(quantity)
        .with_for_update(skip_locked=True)
    )
    result = await session.execute(stmt)
    items = list(result.scalars().all())

    if len(items) < quantity:
        raise ValueError(
            f"Estoque insuficiente: solicitado={quantity}, disponível={len(items)}"
        )

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=reservation_minutes)

    for item in items:
        item.status = "RESERVED"
        item.reserved_by_user_id = user_id
        item.reserved_at = now
        item.reservation_expires_at = expires_at

    await session.commit()
    logger.info(
        f"{len(items)} item(ns) reservados para user_id={user_id}, product_id={product_id}"
    )
    return items


async def release_expired_reservations(
    session: AsyncSession,
    tenant_id: UUID,
) -> int:
    """
    Libera reservas expiradas, retornando os itens para AVAILABLE.
    """
    now = datetime.now(timezone.utc)
    stmt = (
        select(InventoryItem)
        .where(
            InventoryItem.tenant_id == tenant_id,
            InventoryItem.status == "RESERVED",
            InventoryItem.reservation_expires_at < now,
        )
        .with_for_update(skip_locked=True)
    )
    result = await session.execute(stmt)
    items = list(result.scalars().all())

    for item in items:
        item.status = "AVAILABLE"
        item.reserved_by_user_id = None
        item.reserved_at = None
        item.reservation_expires_at = None

    if items:
        await session.commit()
        logger.info(f"{len(items)} reserva(s) expirada(s) liberada(s) para tenant_id={tenant_id}")

    return len(items)


async def cancel_reservation(
    session: AsyncSession,
    tenant_id: UUID,
    user_id: UUID,
    product_id: UUID,
) -> int:
    """
    Cancela a reserva de um usuário para um produto, liberando os itens.
    """
    stmt = (
        select(InventoryItem)
        .where(
            InventoryItem.tenant_id == tenant_id,
            InventoryItem.product_id == product_id,
            InventoryItem.status == "RESERVED",
            InventoryItem.reserved_by_user_id == user_id,
        )
        .with_for_update(skip_locked=True)
    )
    result = await session.execute(stmt)
    items = list(result.scalars().all())

    for item in items:
        item.status = "AVAILABLE"
        item.reserved_by_user_id = None
        item.reserved_at = None
        item.reservation_expires_at = None

    if items:
        await session.commit()
        logger.info(f"{len(items)} reserva(s) cancelada(s) para user_id={user_id}, product_id={product_id}")

    return len(items)


async def mark_items_as_sold(
    session: AsyncSession,
    tenant_id: UUID,
    user_id: UUID,
    product_id: UUID,
    sold_item_ids: List[UUID],
) -> int:
    """
    Marca itens reservados como SOLD após a confirmação da compra.
    """
    if not sold_item_ids:
        return 0

    stmt = (
        select(InventoryItem)
        .where(
            InventoryItem.tenant_id == tenant_id,
            InventoryItem.product_id == product_id,
            InventoryItem.id.in_(sold_item_ids),
            InventoryItem.status == "RESERVED",
            InventoryItem.reserved_by_user_id == user_id,
        )
        .with_for_update(skip_locked=True)
    )
    result = await session.execute(stmt)
    items = list(result.scalars().all())

    now = datetime.now(timezone.utc)
    for item in items:
        item.status = "SOLD"
        item.sold_to_user_id = user_id
        item.sold_at = now
        item.reserved_by_user_id = None
        item.reserved_at = None
        item.reservation_expires_at = None

    if items:
        await session.commit()
        logger.info(f"{len(items)} item(ns) vendido(s) para user_id={user_id}, product_id={product_id}")

    return len(items)


async def add_stock_items(
    session: AsyncSession,
    tenant_id: UUID,
    product_id: UUID,
    items_data: List[dict],
) -> List[InventoryItem]:
    """
    Adiciona novos itens ao estoque de um produto.
    """
    created_items = []
    for data in items_data:
        item = InventoryItem(
            tenant_id=tenant_id,
            product_id=product_id,
            status="AVAILABLE",
            email_encrypted=data.get("email_encrypted"),
            password_encrypted=data.get("password_encrypted"),
            note_encrypted=data.get("note_encrypted"),
            reference=data.get("reference"),
        )
        session.add(item)
        created_items.append(item)

    await session.commit()
    logger.info(f"{len(created_items)} item(ns) adicionado(s) ao product_id={product_id}")
    return created_items


async def get_reserved_items_for_user(
    session: AsyncSession,
    tenant_id: UUID,
    user_id: UUID,
) -> List[InventoryItem]:
    """
    Lista itens RESERVED de um usuário.
    """
    stmt = select(InventoryItem).where(
        InventoryItem.tenant_id == tenant_id,
        InventoryItem.reserved_by_user_id == user_id,
        InventoryItem.status == "RESERVED",
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
