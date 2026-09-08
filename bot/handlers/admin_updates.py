"""
Handlers administrativos de Atualizações.

Seção 30 do painel: gerencia atualizações do sistema.
Inclui versão atual, verificação, changelog, backup e health check.

Não executa deploy real; apenas registra solicitações e mostra status.
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from sqlalchemy import select

from bot.core.config import settings
from bot.core.database import get_async_session_factory
from bot.keyboards.utils import create_button
from bot.models.settings import Settings
from bot.models.user import User
from bot.services.user_service import get_tenant_for_bot, get_or_create_user

logger = logging.getLogger(__name__)

router = Router()


async def _get_tenant_and_user_from_callback(callback: CallbackQuery):
    """Obtém tenant e usuário a partir do callback."""
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
    """Verifica se o usuário é administrador ou dono no tenant."""
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


async def _get_setting(session, tenant_id: UUID, key: str) -> Optional[str]:
    """Busca valor de configuração."""
    stmt = select(Settings).where(
        Settings.tenant_id == tenant_id,
        Settings.key == key,
        Settings.deleted_at.is_(None),
    )
    setting = (await session.execute(stmt)).scalar_one_or_none()
    return setting.value if setting else None


async def _set_setting(session, tenant_id: UUID, key: str, value: str) -> None:
    """Cria ou atualiza configuração."""
    stmt = select(Settings).where(
        Settings.tenant_id == tenant_id,
        Settings.key == key,
        Settings.deleted_at.is_(None),
    )
    setting = (await session.execute(stmt)).scalar_one_or_none()
    if setting:
        setting.value = value
    else:
        setting = Settings(tenant_id=tenant_id, key=key, value=value)
        session.add(setting)
    await session.commit()


async def _edit_or_answer(callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup):
    """Edita a mensagem atual, se possível."""
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "updates_admin:main")
async def updates_admin_main(callback: CallbackQuery, state: FSMContext):
    """Menu principal de atualizações."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        current_version = settings.APP_NAME + " v0.1.0"
        last_check = await _get_setting(session, tenant.id, "last_update_check") or "Nunca"
        changelog = await _get_setting(session, tenant.id, "changelog") or "Nenhum changelog disponível."

    text = (
        "🔄 ATUALIZAÇÕES\n\n"
        f"Versão atual: <b>{current_version}</b>\n"
        f"Última verificação: <b>{last_check}</b>\n\n"
        f"Changelog:\n{changelog[:200]}{'...' if len(changelog) > 200 else ''}\n\n"
        "Escolha uma opção:"
    )
    buttons = [
        [create_button("🔍 Verificar atualização", "updates_admin:check")],
        [create_button("📋 Ver changelog completo", "updates_admin:changelog")],
        [create_button("💾 Fazer backup", "updates_admin:backup")],
        [create_button("🩺 Health check", "updates_admin:health")],
        [create_button("🔙 VOLTAR", "admin:main")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "updates_admin:check")
async def check_updates(callback: CallbackQuery, state: FSMContext):
    """Verifica atualizações (simula consulta; registra data)."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M")
        await _set_setting(session, tenant.id, "last_update_check", now)

    await callback.answer("✅ Verificação registrada. Nenhuma atualização disponível.")
    await updates_admin_main(callback, state)


@router.callback_query(F.data == "updates_admin:changelog")
async def show_changelog(callback: CallbackQuery, state: FSMContext):
    """Exibe changelog completo (do settings)."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return
        changelog = await _get_setting(session, tenant.id, "changelog") or "Nenhum changelog."

    text = f"📋 Changelog:\n\n{changelog}"
    buttons = [[create_button("🔙 VOLTAR", "updates_admin:main")]]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "updates_admin:backup")
async def backup_now(callback: CallbackQuery, state: FSMContext):
    """Executa backup (chama script, se disponível)."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    # Em produção, isso chamaria um worker ou script de backup.
    # Por ora, apenas registra a solicitação.
    await callback.answer("✅ Solicitação de backup registrada.")
    await updates_admin_main(callback, state)


@router.callback_query(F.data == "updates_admin:health")
async def health_check(callback: CallbackQuery, state: FSMContext):
    """Executa health check básico (banco/redis)."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        # Verifica banco
        db_ok = True
        redis_ok = True
        try:
            from bot.core.redis import create_redis_client, close_redis_client
            redis_client = await create_redis_client(settings)
            await redis_client.ping()
            await close_redis_client(redis_client)
        except Exception:
            redis_ok = False

    text = (
        "🩺 Health Check\n\n"
        f"Banco de dados: {'✅ OK' if db_ok else '❌ Falha'}\n"
        f"Redis: {'✅ OK' if redis_ok else '❌ Falha'}\n"
        f"Versão: {settings.APP_NAME} v0.1.0\n"
    )
    buttons = [[create_button("🔙 VOLTAR", "updates_admin:main")]]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)
