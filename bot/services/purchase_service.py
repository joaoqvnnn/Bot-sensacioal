"""
Serviço de compra (atualizado).

Orquestra o fluxo completo de compra de um produto:
- Verifica disponibilidade de estoque
- Calcula valor total
- Se saldo suficiente: debita, cria pedido, marca estoque como SOLD
- Se saldo insuficiente: retorna diferença para gerar Pix (sem concluir)
- Após concluir, gera entrega (DeliveryJob), token de acesso e notifica canal.
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.order import Order, OrderItem
from bot.models.product import Product
from bot.models.user import User
from bot.services.inventory_service import (
    reserve_items,
    mark_items_as_sold,
    cancel_reservation,
)
from bot.services.wallet_service import (
    get_balance,
    debit_wallet,
)
from bot.services.delivery_service import create_delivery_for_order
from bot.services.channel_notifier import notify_purchase_completed

logger = logging.getLogger(__name__)


async def purchase_product(
    session: AsyncSession,
    tenant_id: UUID,
    user: User,
    product: Product,
    quantity: int = 1,
    delivery_method: str = "TELEGRAM",
    bot=None,  # instância do Bot para notificações
) -> dict:
    """
    Executa a compra de um produto para um usuário.

    Fluxo:
    1. Verifica se há estoque disponível.
    2. Calcula valor total.
    3. Se saldo suficiente:
       - Debita saldo
       - Marca itens como SOLD
       - Cria pedido e itens
       - Gera entrega (DeliveryJob e ProductAccessToken)
       - Notifica canal de compras (se configurado)
       - Retorna status "COMPLETED"
    4. Se saldo insuficiente:
       - Retorna "INSUFFICIENT_FUNDS" com valor faltante

    Args:
        session: Sessão do banco.
        tenant_id: ID do tenant.
        user: Instância do usuário comprador.
        product: Instância do produto.
        quantity: Quantidade desejada.
        delivery_method: Método de entrega preferido (TELEGRAM, WHATSAPP, EMAIL).
        bot: Instância do Bot (opcional, para envio de notificações).

    Returns:
        dict: Resultado da operação com status e dados.
    """
    # Validações
    if quantity <= 0:
        raise ValueError("Quantidade deve ser maior que zero.")

    # Verifica saldo
    balance_cents = await get_balance(session, tenant_id, user.id)
    total_cents = int(product.price_cents) * quantity

    if balance_cents < total_cents:
        # Saldo insuficiente
        missing_cents = total_cents - balance_cents
        return {
            "status": "INSUFFICIENT_FUNDS",
            "balance_cents": balance_cents,
            "total_cents": total_cents,
            "missing_cents": missing_cents,
        }

    # Saldo suficiente: tenta reservar estoque
    try:
        reserved_items = await reserve_items(
            session,
            tenant_id=tenant_id,
            product_id=product.id,
            user_id=user.id,
            quantity=quantity,
            reservation_minutes=10,
        )
    except ValueError as e:
        logger.warning(f"Falha ao reservar estoque: {e}")
        return {"status": "OUT_OF_STOCK", "message": str(e)}

    # Debita saldo
    try:
        await debit_wallet(
            session,
            tenant_id=tenant_id,
            user_id=user.id,
            amount_cents=total_cents,
            entry_type="purchase",
            description=f"Compra de {product.name} x{quantity}",
            reference_id=None,
        )
    except Exception as e:
        await cancel_reservation(
            session,
            tenant_id=tenant_id,
            user_id=user.id,
            product_id=product.id,
        )
        logger.error(f"Erro ao debitar saldo, reserva cancelada: {e}")
        raise

    # Marca itens como vendidos
    sold_count = await mark_items_as_sold(
        session,
        tenant_id=tenant_id,
        user_id=user.id,
        product_id=product.id,
        sold_item_ids=[item.id for item in reserved_items],
    )
    if sold_count != quantity:
        logger.error(f"Inconsistência: esperado {quantity} vendidos, mas {sold_count} marcados.")
        await debit_wallet(
            session,
            tenant_id=tenant_id,
            user_id=user.id,
            amount_cents=-total_cents,
            entry_type="reversal",
            description=f"Estorno por inconsistência na compra de {product.name}",
        )
        await cancel_reservation(
            session,
            tenant_id=tenant_id,
            user_id=user.id,
            product_id=product.id,
        )
        return {"status": "FAILED", "message": "Inconsistência no estoque."}

    # Cria pedido
    order = Order(
        tenant_id=tenant_id,
        user_id=user.id,
        status="COMPLETED",
        total_cents=total_cents,
        paid_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
    )
    session.add(order)
    await session.flush()

    # Cria itens do pedido
    for item in reserved_items:
        order_item = OrderItem(
            tenant_id=tenant_id,
            order_id=order.id,
            product_id=product.id,
            inventory_item_id=item.id,
            unit_price_cents=int(product.price_cents),
            quantity=1,
            product_name=product.name,
            product_description=product.description,
        )
        session.add(order_item)

    await session.commit()
    await session.refresh(order)

    logger.info(f"Compra concluída: order_id={order.id}, user_id={user.id}, total={total_cents}")

    # Gera entrega e token de acesso
    delivery_info = None
    try:
        delivery_info = await create_delivery_for_order(
            session,
            tenant_id=tenant_id,
            order=order,
            user=user,
            method=delivery_method,
        )
    except Exception as e:
        logger.exception(f"Erro ao gerar entrega para order_id={order.id}: {e}")

    # Notifica canal de compras (se bot fornecido)
    if bot:
        try:
            await notify_purchase_completed(tenant_id, order, bot)
        except Exception as e:
            logger.exception(f"Erro ao notificar canal para order_id={order.id}: {e}")

    return {
        "status": "COMPLETED",
        "order_id": order.id,
        "total_cents": total_cents,
        "items_sold": sold_count,
        "delivery": delivery_info,
    }
