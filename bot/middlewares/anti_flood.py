"""
Middleware de anti-flood.

Protege o bot contra spam de mensagens, callbacks, comandos e entradas.
Usa Redis para contagem de ações por usuário em janela deslizante.
Os limites são lidos da tabela Settings (se existirem) e podem ser
alterados pelo painel administrativo em tempo real, sem reiniciar o bot.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Union

from aiogram import Bot
from aiogram.types import Message, CallbackQuery, Update
from redis.asyncio import Redis

from bot.core.config import settings
from bot.models.anti_flood import AntiFloodEvent
from bot.models.user_block import UserBlock
from bot.models.user import User
from bot.models.settings import Settings
from bot.core.database import get_async_session_factory
from bot.services.user_service import get_tenant_for_bot

logger = logging.getLogger(__name__)


class AntiFloodMiddleware:
    """
    Middleware para controle de fluxo por usuário.

    Parâmetros podem ser carregados do banco (Settings):
    - antiflood_enabled: "true" ou "false"
    - antiflood_max_actions: máximo de ações por janela
    - antiflood_window_seconds: duração da janela em segundos
    - antiflood_block_seconds: duração do bloqueio temporário (0 = permanente)
    """

    def __init__(self, redis: Redis):
        self.redis = redis

    async def _get_setting(self, session, tenant_id, key: str, default: str) -> str:
        """Busca configuração do tenant, com fallback."""
        if tenant_id is None:
            return default
        from sqlalchemy import select
        stmt = select(Settings).where(
            Settings.tenant_id == tenant_id,
            Settings.key == key,
            Settings.deleted_at.is_(None),
        )
        result = await session.execute(stmt)
        setting = result.scalar_one_or_none()
        return setting.value if setting else default

    async def __call__(self, handler, event: Update, data: dict):
        """
        Processa o evento, verificando rate limit antes de passar ao handler.
        """
        user_id = self._extract_user_id(event)
        if user_id is None:
            return await handler(event, data)

        # Obtém tenant a partir do bot username
        bot: Bot = data.get("bot")
        tenant = None
        if bot and bot.username:
            async with get_async_session_factory() as session:
                tenant = await get_tenant_for_bot(session, bot.username)

        # Se não houver tenant, usa defaults
        if tenant is None:
            max_actions = 10
            window_seconds = 10
            block_seconds = 60
            enabled = True
        else:
            async with get_async_session_factory() as session:
                enabled_str = await self._get_setting(session, tenant.id, "antiflood_enabled", "true")
                max_actions = int(await self._get_setting(session, tenant.id, "antiflood_max_actions", "10"))
                window_seconds = int(await self._get_setting(session, tenant.id, "antiflood_window_seconds", "10"))
                block_seconds = int(await self._get_setting(session, tenant.id, "antiflood_block_seconds", "60"))
                enabled = enabled_str == "true"

        if not enabled:
            return await handler(event, data)

        # Chave no Redis
        key = f"antiflood:{tenant.id if tenant else 'global'}:{user_id}"

        # Incrementa contagem e define expiração se necessário
        current = await self.redis.incr(key)
        if current == 1:
            await self.redis.expire(key, window_seconds)

        # Se excedeu, bloqueia
        if current > max_actions:
            await self._block_user(tenant, user_id, event, block_seconds)
            return

        # Caso contrário, passa adiante
        return await handler(event, data)

    def _extract_user_id(self, event: Update) -> Optional[int]:
        """Extrai ID do usuário do evento, se possível."""
        if isinstance(event, Message):
            return event.from_user.id if event.from_user else None
        elif isinstance(event, CallbackQuery):
            return event.from_user.id if event.from_user else None
        return None

    async def _block_user(self, tenant, telegram_id: int, event: Update, block_seconds: int):
        """
        Registra bloqueio no banco e notifica o usuário.
        """
        if tenant is None:
            return

        now = datetime.now(timezone.utc)
        unblock_at = now + timedelta(seconds=block_seconds) if block_seconds > 0 else None

        async with get_async_session_factory() as session:
            # Busca usuário pelo telegram_id
            from sqlalchemy import select
            user = (await session.execute(
                select(User).where(
                    User.tenant_id == tenant.id,
                    User.telegram_id == telegram_id,
                    User.deleted_at.is_(None),
                )
            )).scalar_one_or_none()

            if user:
                # Cria evento de anti-flood
                anti_event = AntiFloodEvent(
                    tenant_id=tenant.id,
                    user_id=user.id,
                    trigger_type="message",
                    actions_count=10,  # valor aproximado
                    interval_seconds=10,
                    block_duration_seconds=block_seconds,
                    blocked_at=now,
                    unblock_at=unblock_at,
                )
                session.add(anti_event)

                # Cria bloqueio de usuário
                user_block = UserBlock(
                    tenant_id=tenant.id,
                    user_id=user.id,
                    block_type="TEMPORARY" if block_seconds > 0 else "PERMANENT",
                    reason="Anti-flood",
                    expires_at=unblock_at,
                    blocked_by_user_id=None,
                    is_active=True,
                )
                session.add(user_block)

                # Marca usuário como bloqueado (campo no modelo User)
                user.is_blocked = True
                user.block_reason = "Anti-flood"

                await session.commit()

        # Envia mensagem de bloqueio
        text = (
            "🚫 Você foi temporariamente bloqueado.\n"
            "Motivo: Anti-flood.\n"
            f"Tente novamente em {block_seconds} segundos."
        )
        if isinstance(event, Message):
            await event.answer(text)
        elif isinstance(event, CallbackQuery):
            await event.answer(text, show_alert=True)
