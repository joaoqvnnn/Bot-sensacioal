"""
Serviço de compra.

Orquestra o fluxo completo de compra de um produto:
- Verifica disponibilidade de estoque
- Calcula valor total
- Se saldo suficiente: debita, cria pedido, marca estoque como SOLD
- Se saldo insuficiente: retorna diferença para gerar Pix (sem concluir)
- Após concluir, gera entrega (DeliveryJob) e token de acesso (ProductAccessToken)
"""

import logging
from datetime import datetime, timezone
from typing import Optional, Tuple
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

logger = logging.getLogger(__name__)


async def purchase_product(
    session: AsyncSession,
    tenant_id: UUID,
    user: User,
    product: Product,
    quantity: int = 1,
    delivery_method: str = "TELEGRAM",
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
       - Retorna status "COMPLETED"
    4. Se saldo insuficiente:
       - Retorna "INSUFFICIENT_FUNDS" com valor faltante
         (não reserva estoque; reserva somente quando pagamento for feito)

    Args:
        session: Sessão do banco.
        tenant_id: ID do tenant.
        user: Instância do usuário comprador.
        product: Instância do produto.
        quantity: Quantidade desejada.
        delivery_method: Método de entrega preferido (TELEGRAM, WHATSAPP, EMAIL).

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
            reservation_minutes=10,  # deve ser configurável
        )
    except ValueError as e:
        logger.warning(f"Falha ao reservar estoque: {e}")
        return {
            "status": "OUT_OF_STOCK",
            "message": str(e),
        }

    # Debita saldo
    try:
        ledger_entry = await debit_wallet(
            session,
            tenant_id=tenant_id,
            user_id=user.id,
            amount_cents=total_cents,
            entry_type="purchase",
            description=f"Compra de {product.name} x{quantity}",
            reference_id=None,
        )
    except Exception as e:
        # Se falhar débito, libera reserva
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
        # Inconsistência: reverter débito e cancelar reserva
        logger.error(f"Inconsistência: esperado {quantity} vendidos, mas {sold_count} marcados.")
        # Estorna débito
        await debit_wallet(
            session,
            tenant_id=tenant_id,
            user_id=user.id,
            amount_cents=-total_cents,  # estorno
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
    await session.flush()  # para obter ID

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

    # Commit principal da compra (pedido e itens)
    await session.commit()
    await session.refresh(order)

    logger.info(f"Compra concluída: order_id={order.id}, user_id={user.id}, total={total_cents}")

    # Gera entrega e token de acesso (após commit da compra, mas dentro da mesma sessão)
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
        # A compra já está concluída; o erro não reverte a compra.
        # Em produção, pode-se agendar retry.

    return {
        "status": "COMPLETED",
        "order_id": order.id,
        "total_cents": total_cents,
        "items_sold": sold_count,
        "delivery": delivery_info,
    }
