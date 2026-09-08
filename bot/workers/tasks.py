"""
Configuração de tarefas assíncronas (arq).

Define as funções de tarefas que serão executadas pelos workers:
- process_payment_task: processa confirmação de pagamento vinda do webhook
- release_expired_reservations_task: libera reservas de estoque expiradas
- send_delivery_task: processa entregas pendentes (Telegram, WhatsApp, e-mail)
- process_notifications_task: processa notificações programadas
- process_alerts_task: processa alertas de estoque
- process_broadcast_task: processa fila de transmissões em massa

Todas as tarefas usam sessão do banco e serviços existentes.
"""

import logging
from typing import Any, Dict, Optional
from uuid import UUID

from arq import create_pool
from arq.connections import RedisSettings

from bot.core.config import settings
from bot.core.database import get_async_session_factory
from bot.core.redis import create_redis_client
from bot.services.payment_service import process_payment_webhook
from bot.services.inventory_service import release_expired_reservations
from bot.workers.delivery_worker import send_delivery_task
from bot.workers.notification_worker import process_notifications_task
from bot.workers.alert_worker import process_alerts_task
from bot.workers.broadcast_worker import process_broadcast_task

logger = logging.getLogger(__name__)


async def process_payment_task(
    ctx: Dict[str, Any],
    tenant_id: str,
    payment_id: str,
    external_status: str,
    provider_response: Optional[str] = None,
) -> None:
    """
    Processa pagamento confirmado via webhook (tarefa em worker).
    """
    async with get_async_session_factory() as session:
        try:
            await process_payment_webhook(
                session=session,
                tenant_id=UUID(tenant_id),
                payment_id=UUID(payment_id),
                external_status=external_status,
                provider_response=provider_response,
            )
            logger.info(f"Pagamento {payment_id} processado com sucesso.")
        except Exception as e:
            logger.exception(f"Erro ao processar pagamento {payment_id}: {e}")


async def release_expired_reservations_task(ctx: Dict[str, Any], tenant_id: str) -> int:
    """
    Libera reservas expiradas para um tenant.
    """
    async with get_async_session_factory() as session:
        try:
            count = await release_expired_reservations(session, UUID(tenant_id))
            logger.info(f"{count} reservas expiradas liberadas para tenant {tenant_id}.")
            return count
        except Exception as e:
            logger.exception(f"Erro ao liberar reservas expiradas: {e}")
            return 0


async def send_delivery_task(
    ctx: Dict[str, Any],
    delivery_job_id: str,
    bot=None,
) -> bool:
    """
    Processa um job de entrega pendente.
    """
    from bot.workers.delivery_worker import send_delivery_task as _send
    return await _send(ctx, delivery_job_id, bot)


async def process_notifications_task(
    ctx: Dict[str, Any],
    tenant_id: str,
    bot=None,
) -> int:
    """
    Processa notificações programadas.
    """
    from bot.workers.notification_worker import process_notifications_task as _process
    return await _process(ctx, tenant_id, bot)


async def process_alerts_task(
    ctx: Dict[str, Any],
    tenant_id: str,
    bot=None,
) -> int:
    """
    Processa alertas de estoque.
    """
    from bot.workers.alert_worker import process_alerts_task as _alert
    return await _alert(ctx, tenant_id, bot)


async def process_broadcast_task(
    ctx: Dict[str, Any],
    tenant_id: str,
    broadcast_id: str,
    bot=None,
) -> bool:
    """
    Processa uma transmissão em massa.
    """
    from bot.workers.broadcast_worker import process_broadcast_task as _broadcast
    return await _broadcast(ctx, tenant_id, broadcast_id, bot)


async def startup(ctx: Dict[str, Any]) -> None:
    """Inicializa conexões no worker."""
    pass


async def shutdown(ctx: Dict[str, Any]) -> None:
    """Encerra conexões."""
    pass


class WorkerSettings:
    """
    Configuração das funções de tarefas para o arq.
    """
    functions = [
        process_payment_task,
        release_expired_reservations_task,
        send_delivery_task,
        process_notifications_task,
        process_alerts_task,
        process_broadcast_task,
        # Futuras tarefas:
        # send_broadcast_task,
        # process_withdrawal_task,
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        password=settings.REDIS_PASSWORD.get_secret_value(),
        database=settings.REDIS_DB,
    )
