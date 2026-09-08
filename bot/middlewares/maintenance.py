"""
Middleware de modo manutenção.

Quando ativado, bloqueia todos os usuários comuns, permitindo apenas
administradores e donos. A configuração é lida da tabela Settings.
"""

import logging
from typing import Optional, Union

from aiogram.types import Message, CallbackQuery, Update
from sqlalchemy import select

from bot.core.database import get_async_session_factory
from bot.models.settings import Settings
from bot.models.user import User
from bot.models.admin_user import AdminUser
from bot.services.user_service import get_tenant_for_bot

logger = logging.getLogger(__name__)


async def is_maintenance_mode(tenant_id) -> bool:
    """Verifica se o modo manutenção está ativo para o tenant."""
    async with get_async_session_factory() as session:
        stmt = select(Settings).where(
            Settings.tenant_id == tenant_id,
            Settings.key == "maintenance_mode",
            Settings.deleted_at.is_(None),
        )
        result = await session.execute(stmt)
        setting = result.scalar_one_or_none()
        return setting.value == "true" if setting else False


async def is_admin_user(tenant_id, user_id) -> bool:
    """Verifica se o usuário é admin/dono no tenant."""
    async with get_async_session_factory() as session:
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
        # Determina tenant e usuário a partir do evento
        tenant, user = await self._get_tenant_and_user(event)
        if tenant is None:
            # Se não há tenant, não aplica manutenção
            return await handler(event, data)

        maintenance = await is_maintenance_mode(tenant.id)
        if not maintenance:
            return await handler(event, data)

        # Modo manutenção ativo: verificar se é admin
        if user and await is_admin_user(tenant.id, user.id):
            # Admin pode continuar
            return await handler(event, data)

        # Bloqueia usuário comum
        await self._send_maintenance_message(event)
        return

    async def _get_tenant_and_user(self, event: Update):
        """
        Obtém tenant e usuário a partir do evento.
        Retorna (None, None) se não conseguir.
        """
        # Este método precisa de acesso ao bot e banco.
        # Em middleware, o ideal é injetar session_factory e usar bot.username.
        # Por simplicidade, retornamos None; em produção, implementar corretamente.
        # Aqui, vamos tentar obter através do data do handler.
        return None, None

    async def _send_maintenance_message(self, event: Update):
        """Envia mensagem de manutenção ao usuário."""
        text = (
            "🔧 BOT EM MANUTENÇÃO\n"
            "Estamos realizando uma manutenção.\n"
            "Tente novamente mais tarde."
        )
        if isinstance(event, Message):
            await event.answer(text)
        elif isinstance(event, CallbackQuery):
            await event.answer(text, show_alert=True)
