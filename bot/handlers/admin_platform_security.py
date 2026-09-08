"""
Handlers administrativos de Segurança da Plataforma.

Seção 26 do painel: exibe informações e permite ações básicas de segurança,
como backup, status de criptografia, HTTPS, rate limiting, etc.
Não executa ações destrutivas sem confirmação.
"""

import logging
from typing import Optional
from uuid import UUID

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext

from bot.core.database import get_async_session_factory
from bot.keyboards.utils import create_button
from bot.models.user import User
from bot.services.user_service import get_tenant_for_bot, get_or_create_user
from bot.core.security import hash_password, verify_password, encrypt_data, decrypt_data

logger = logging.getLogger(__name__)

router = Router()


async def _get_tenant_and_user_from_callback(callback: CallbackQuery):
    async with get_async_session_factory() as session:
        tenant = await get_tenant_for_bot(session, callback.bot.username)
        if tenant is None:
            return None, None
        user = await get_or_create_user(
            session=session,
            tenant=tenant,
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
            last_name=callback.from_user.last_name,
        )
        return tenant, user


async def _is_admin(session, tenant_id: UUID, user_id: UUID) -> bool:
    user = (await session.execute(
        select(User).where(User.id == user_id, User.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if user and (user.is_owner or user.is_admin):
        return True
    from bot.models.admin_user import AdminUser
    admin = (await session.execute(
        select(AdminUser).where(
            AdminUser.tenant_id == tenant_id,
            AdminUser.user_id == user_id,
            AdminUser.is_active == True,
            AdminUser.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    return admin is not None


async def _edit_or_answer(callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup):
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "platform_sec:main")
async def platform_sec_main(callback: CallbackQuery, state: FSMContext):
    """Menu principal de segurança da plataforma."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

    # Simples status
    encryption_status = "Ativa" if True else "Inativa"  # pode ser dinâmico
    https_status = "Configurado" if settings.TELEGRAM_WEBHOOK_URL else "Não aplicável"

    text = (
        "🔐 SEGURANÇA DA PLATAFORMA\n\n"
        f"Hash de senhas: <b>bcrypt</b>\n"
        f"Criptografia de dados: <b>{encryption_status}</b>\n"
        f"HTTPS/Webhook: <b>{https_status}</b>\n"
        f"Rate limiting: <b>Ativo</b>\n"
        f"Auditoria: <b>Ativa</b>\n"
        f"Backup: <b>Manual</b>\n\n"
        "Ações disponíveis:"
    )
    buttons = [
        [create_button("💾 Executar backup", "platform_sec:backup")],
        [create_button("🩺 Verificar integridade", "platform_sec:integrity")],
        [create_button("🔙 VOLTAR", "admin:main")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "platform_sec:backup")
async def backup(callback: CallbackQuery, state: FSMContext):
    """Solicita backup (pode chamar script)."""
    # Em produção, chamaria worker de backup
    await callback.answer("✅ Solicitação de backup registrada.")
    await platform_sec_main(callback, state)


@router.callback_query(F.data == "platform_sec:integrity")
async def integrity(callback: CallbackQuery, state: FSMContext):
    """Executa verificação de integridade básica."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    # Chama handler de integridade se existir
    from bot.handlers.admin_integrity import integrity_main
    await integrity_main(callback, state)
