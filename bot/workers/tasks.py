"""
Configuração de tarefas assíncronas (arq).

Define as funções de tarefas que serão executadas pelos workers:
- process_payment_webhook: processa confirmação de pagamento vinda do webhook
- release_expired_reservations: libera reservas de estoque expiradas
- send_delivery: envia entrega ao usuário (Telegram, WhatsApp, e-mail)
- send_broadcast: envia transmissão em massa
- process_withdrawal: processa saque solicitado

Todas as tarefas usam sessão do banco e serviços existentes.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from arq import create_pool
from arq.connections import RedisSettings

from bot.core.config import settings
from bot.core.database import get_async_session_factory
from bot.core.redis import create_redis_client
from bot.services.payment_service import process_payment_webhook
from bot.services.inventory_service import release_expired_reservations

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

    Args:
        ctx: Contexto do arq (contém redis e outras dependências).
        tenant_id: ID do tenant (string).
        payment_id: ID interno do pagamento (string).
        external_status: Status informado pelo provedor.
        provider_response: Resposta bruta (opcional).
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

    Args:
        ctx: Contexto do arq.
        tenant_id: ID do tenant.

    Returns:
        int: Quantidade de reservas liberadas.
    """
    async with get_async_session_factory() as session:
        try:
            count = await release_expired_reservations(session, UUID(tenant_id))
            logger.info(f"{count} reservas expiradas liberadas para tenant {tenant_id}.")
            return count
        except Exception as e:
            logger.exception(f"Erro ao liberar reservas expiradas: {e}")
            return 0


async def startup(ctx: Dict[str, Any]) -> None:
    """Inicializa conexões no worker."""
    # Redis já é injetado pelo arq automaticamente.
    pass


async def shutdown(ctx: Dict[str, Any]) -> None:
    """Encerra conexões."""
    pass


# Configuração do pool de workers (usada em bot/workers/__init__.py)
async def get_worker_pool():
    """Cria e retorna um pool de workers arq."""
    redis_settings = RedisSettings(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        password=settings.REDIS_PASSWORD.get_secret_value(),
        database=settings.REDIS_DB,
    )
    return await create_pool(redis_settings)


class WorkerSettings:
    """
    Configuração das funções de tarefas para o arq.
    """
    functions = [
        process_payment_task,
        release_expired_reservations_task,
        # Adicionar outras tarefas conforme implementação:
        # send_delivery_task,
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
