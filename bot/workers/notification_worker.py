"""
Worker de notificações programadas.

Tarefa que processa notificações pendentes para um tenant.
Usa o serviço notification_service.
"""

import logging
from typing import Any, Dict, Optional
from uuid import UUID

from bot.core.database import get_async_session_factory
from bot.services.notification_service import process_due_notifications

logger = logging.getLogger(__name__)


async def process_notifications_task(
    ctx: Dict[str, Any],
    tenant_id: str,
    bot=None,
) -> int:
    """
    Processa notificações programadas vencidas.

    Args:
        ctx: Contexto do arq.
        tenant_id: ID do tenant (string).
        bot: Instância do Bot (opcional, pode ser injetada).

    Returns:
        int: Quantidade processada.
    """
    async with get_async_session_factory() as session:
        try:
            count = await process_due_notifications(
                session=session,
                tenant_id=UUID(tenant_id),
                bot=bot,
            )
            logger.info(f"{count} notificações processadas para tenant {tenant_id}.")
            return count
        except Exception as e:
            logger.exception(f"Erro ao processar notificações: {e}")
            return 0
