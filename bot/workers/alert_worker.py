"""
Worker de alertas de estoque.

Processa produtos que voltaram a ter estoque e notifica os usuários
que assinaram alertas. Usa o serviço de inventário para verificar
disponibilidade e envia mensagem via bot.
"""

import logging
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy import select

from bot.core.database import get_async_session_factory
from bot.models.alert import AlertSubscription
from bot.models.inventory_item import InventoryItem
from bot.models.product import Product
from bot.models.user import User

logger = logging.getLogger(__name__)


async def process_alerts_task(
    ctx: Dict[str, Any],
    tenant_id: str,
    bot=None,
) -> int:
    """
    Verifica produtos com estoque e notifica assinantes.

    Args:
        ctx: Contexto do arq.
        tenant_id: ID do tenant (string).
        bot: Instância do Bot (opcional).

    Returns:
        int: Quantidade de alertas enviados.
    """
    async with get_async_session_factory() as session:
        tenant_uuid = UUID(tenant_id)

        # Busca todos os alertas ativos
        alert_stmt = select(AlertSubscription).where(
            AlertSubscription.tenant_id == tenant_uuid,
            AlertSubscription.is_active == True,
            AlertSubscription.deleted_at.is_(None),
        )
        alerts = (await session.execute(alert_stmt)).scalars().all()

        sent_count = 0
        for alert in alerts:
            # Verifica estoque disponível do produto
            stock_stmt = select(InventoryItem).where(
                InventoryItem.tenant_id == tenant_uuid,
                InventoryItem.product_id == alert.product_id,
                InventoryItem.status == "AVAILABLE",
                InventoryItem.deleted_at.is_(None),
            ).limit(1)
            stock = (await session.execute(stock_stmt)).scalars().first()

            if stock is None:
                continue

            # Obtém produto e usuário
            product = (await session.execute(
                select(Product).where(Product.id == alert.product_id)
            )).scalar_one_or_none()
            user = (await session.execute(
                select(User).where(User.id == alert.user_id)
            )).scalar_one_or_none()

            if not product or not user:
                continue

            # Envia notificação
            if bot:
                try:
                    message_text = (
                        f"🔔 Alerta de estoque!\n"
                        f"O produto <b>{product.name}</b> está disponível novamente.\n"
                        f"💵 Preço: R$ {int(product.price_cents)/100:.2f}\n"
                        f"Garanta o seu antes que acabe!"
                    )
                    await bot.send_message(user.telegram_id, message_text, parse_mode="HTML")
                    alert.last_notified_at = datetime.now(timezone.utc)
                    await session.commit()
                    sent_count += 1
                except Exception as e:
                    logger.exception(f"Erro ao enviar alerta para user_id={user.telegram_id}: {e}")

        logger.info(f"{sent_count} alertas enviados para tenant {tenant_uuid}")
        return sent_count
