"""
Middleware de identificação de tenant.

Identifica o tenant ativo a partir do username do bot e injeta
os dados no contexto (data) do handler, para uso em outras camadas.
"""

import logging
from typing import Any, Dict, Optional, Union

from aiogram.types import Message, CallbackQuery, Update
from sqlalchemy import select

from bot.core.database import get_async_session_factory
from bot.models.tenant import Tenant
from bot.services.user_service import get_tenant_for_bot

logger = logging.getLogger(__name__)


class TenantMiddleware:
    """
    Middleware que identifica e injeta o tenant no data do handler.
    """

    async def __call__(self, handler, event: Update, data: Dict[str, Any]):
        """
        Obtém o tenant e adiciona ao data antes de chamar o handler.

        Args:
            handler: Próximo handler.
            event: Evento do Telegram.
            data: Dicionário de dados do handler.

        Returns:
            Resultado do handler.
        """
        bot = data.get("bot")
        if bot is None:
            return await handler(event, data)

        tenant = None
        try:
            async with get_async_session_factory() as session:
                tenant = await get_tenant_for_bot(session, bot.username)
        except Exception as e:
            logger.exception(f"Erro ao identificar tenant: {e}")

        if tenant is not None:
            data["tenant"] = tenant
            data["tenant_id"] = tenant.id
        else:
            data["tenant"] = None
            data["tenant_id"] = None

        return await handler(event, data)
