"""
Middleware de modo manutenção.

Quando ativado, bloqueia todos os usuários comuns, permitindo apenas
administradores e donos. A configuração e as mensagens são lidas
da tabela Settings do tenant correspondente.
"""

import logging
from typing import Optional, Union

from aiogram import Bot
from aiogram.types import Message, CallbackQuery, Update
from sqlalchemy import select

from bot.core.database import get_async_session_factory
from bot.models.settings import Settings
from bot.models.user import User
from bot.models.admin_user import AdminUser
from bot.services.user_service import get_tenant_for_bot, get_or_create_user

logger = logging.getLogger(__name__)


async def _get_setting(session, tenant_id, key: str) -> Optional[str]:
    """Busca valor de configuração."""
    stmt = select(Settings).where(
        Settings.tenant_id == tenant_id,
        Settings.key == key,
        Settings.deleted_at.is_(None),
    )
    setting = (await session.execute(stmt)).scalar_one_or_none()
    return setting.value if setting else None


async def _is_admin_user(session, tenant_id, user_id) -> bool:
    """Verifica se o usuário é admin/dono no tenant."""
    user = (await session.execute(
        select(User).where(User.id == user_id, User.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if user and (user.is_owner or user.is_admin):
        return True

    admin = (await session.execute(
        select(AdminUser).where(
            AdminUser.tenant_id == tenant_id,
            AdminUser.user_id == user_id,
            AdminUser.is_active == True,
            AdminUser.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    return admin is not None


class MaintenanceMiddleware:
    """
    Middleware que bloqueia usuários comuns durante manutenção.
    """

    async def __call__(self, handler, event: Update, data: dict):
        """
        Verifica manutenção antes de passar ao handler.
        """
        bot: Bot = data.get("bot")
        if bot is None:
            return await handler(event, data)

        # Obtém tenant
        tenant = None
        if bot.username:
            async with get_async_session_factory() as session:
                tenant = await get_tenant_for_bot(session, bot.username)

        if tenant is None:
            return await handler(event, data)

        # Verifica status de manutenção
        async with get_async_session_factory() as session:
            maintenance_mode = await _get_setting(session, tenant.id, "maintenance_mode")
            maintenance_message = await _get_setting(session, tenant.id, "maintenance_message") or (
                "🔧 BOT EM MANUTENÇÃO\nEstamos realizando uma manutenção.\nTente novamente mais tarde."
            )

        if maintenance_mode != "true":
            return await handler(event, data)

        # Modo manutenção ativo: verificar se é admin
        user_id = self._extract_user_id(event)
        if user_id is not None:
            async with get_async_session_factory() as session:
                user = (await session.execute(
                    select(User).where(
                        User.tenant_id == tenant.id,
                        User.telegram_id == user_id,
                        User.deleted_at.is_(None),
                    )
                )).scalar_one_or_none()
                if user and await _is_admin_user(session, tenant.id, user.id):
                    # Admin pode continuar
                    return await handler(event, data)

        # Bloqueia usuário comum
        await self._send_maintenance_message(event, maintenance_message)
        return

    def _extract_user_id(self, event: Update) -> Optional[int]:
        if isinstance(event, Message):
            return event.from_user.id if event.from_user else None
        elif isinstance(event, CallbackQuery):
            return event.from_user.id if event.from_user else None
        return None

    async def _send_maintenance_message(self, event: Update, text: str):
        if isinstance(event, Message):
            await event.answer(text)
        elif isinstance(event, CallbackQuery):
            await event.answer(text, show_alert=True)
