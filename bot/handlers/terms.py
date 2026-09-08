"""
Handler de termos de uso.

Permite ao administrador editar o texto dos termos via painel (tabela Settings)
e ao usuário consultar com /termos. Nada fictício: o texto vem do banco.
"""

import logging
from typing import Optional

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.core.database import get_async_session_factory
from bot.models.settings import Settings
from bot.services.user_service import get_tenant_for_bot

logger = logging.getLogger(__name__)

router = Router()


async def _get_terms_text(tenant_id) -> Optional[str]:
    """
    Busca o texto dos termos de uso para o tenant.

    Args:
        tenant_id: ID do tenant.

    Returns:
        Optional[str]: Texto armazenado ou None se não existir.
    """
    from sqlalchemy import select

    async with get_async_session_factory() as session:
        stmt = select(Settings).where(
            Settings.tenant_id == tenant_id,
            Settings.key == "terms_text",
            Settings.deleted_at.is_(None),
        )
        result = await session.execute(stmt)
        setting = result.scalar_one_or_none()
        return setting.value if setting else None


@router.message(Command("termos"))
async def show_terms(message: Message):
    """
    Exibe os termos de uso do bot.

    Args:
        message: Mensagem com o comando /termos.
    """
    tenant = None
    async with get_async_session_factory() as session:
        tenant = await get_tenant_for_bot(session, message.bot.username)

    if tenant is None:
        await message.answer("⚠️ Sistema indisponível.")
        return

    terms_text = await _get_terms_text(tenant.id)
    if not terms_text:
        terms_text = (
            "📄 Termos de Uso\n\n"
            "Os termos ainda não foram configurados pelo administrador.\n"
            "Para mais informações, contate o suporte."
        )

    await message.answer(terms_text)
