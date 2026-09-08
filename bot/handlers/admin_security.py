"""
Handlers administrativos de Segurança e Auditoria.

Seções 25, 26 e 27 do painel: gerencia anti-flood detalhado,
whitelist, lista de bloqueados, desbloqueio e consulta de logs/auditoria.

Tudo persistido na tabela Settings e AuditLog, com edição na mesma mensagem.
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select

from bot.core.database import get_async_session_factory
from bot.keyboards.utils import create_button
from bot.models.settings import Settings
from bot.models.user import User
from bot.models.user_block import UserBlock
from bot.models.audit_log import AuditLog
from bot.services.user_service import get_tenant_for_bot, get_or_create_user

logger = logging.getLogger(__name__)

router = Router()


class AdminSecurityStates(StatesGroup):
    WAITING_VALUE = State()
    WAITING_USER_SEARCH = State()


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


async def _get_tenant_and_user_from_message(message: Message):
    """Obtém tenant e usuário a partir de mensagem."""
    async with get_async_session_factory() as session:
        tenant = await get_tenant_for_bot(session, message.bot.username)
        if tenant is None:
            return None, None
        user = await get_or_create_user(
            session=session,
            tenant=tenant,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
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


@router.callback_query(F.data == "sec_admin:main")
async def security_main(callback: CallbackQuery, state: FSMContext):
    """Menu principal de segurança/anti-flood detalhado."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        # Valores atuais para exibição
        msg_limit = await _get_setting(session, tenant.id, "antiflood_msg_limit") or "10"
        cmd_limit = await _get_setting(session, tenant.id, "antiflood_cmd_limit") or "5"
        callback_limit = await _get_setting(session, tenant.id, "antiflood_callback_limit") or "20"
        input_limit = await _get_setting(session, tenant.id, "antiflood_input_limit") or "5"
        inline_limit = await _get_setting(session, tenant.id, "antiflood_inline_limit") or "10"
        webapp_limit = await _get_setting(session, tenant.id, "antiflood_webapp_limit") or "10"
        block_seconds = await _get_setting(session, tenant.id, "antiflood_block_seconds") or "60"
        permanent_block = await _get_setting(session, tenant.id, "antiflood_permanent_block") or "false"
        block_message = await _get_setting(session, tenant.id, "antiflood_block_message") or "🚫 Bloqueado por anti-flood."

    text = (
        "🛡️ ANTI-FLOOD / SEGURANÇA\n\n"
        f"Limite de mensagens: {msg_limit}\n"
        f"Limite de comandos: {cmd_limit}\n"
        f"Limite de callbacks: {callback_limit}\n"
        f"Limite de inputs: {input_limit}\n"
        f"Limite de inline: {inline_limit}\n"
        f"Limite de WebApp: {webapp_limit}\n"
        f"Tempo de bloqueio (seg): {block_seconds}\n"
        f"Bloqueio permanente: {'Sim' if permanent_block == 'true' else 'Não'}\n"
        f"Mensagem de bloqueio: {block_message[:30]}...\n\n"
        "Escolha uma opção:"
    )
    buttons = [
        [create_button("Alterar limite de mensagens", "sec_admin:set_msg_limit")],
        [create_button("Alterar limite de comandos", "sec_admin:set_cmd_limit")],
        [create_button("Alterar limite de callbacks", "sec_admin:set_callback_limit")],
        [create_button("Alterar limite de inputs", "sec_admin:set_input_limit")],
        [create_button("Alterar limite de inline", "sec_admin:set_inline_limit")],
        [create_button("Alterar limite de WebApp", "sec_admin:set_webapp_limit")],
        [create_button("Alterar tempo de bloqueio", "sec_admin:set_block_time")],
        [create_button("Bloqueio permanente", "sec_admin:toggle_permanent_block")],
        [create_button("Alterar mensagem de bloqueio", "sec_admin:set_block_message")],
        [create_button("Whitelist", "sec_admin:whitelist")],
        [create_button("Lista de bloqueados", "sec_admin:blocked_list")],
        [create_button("Desbloquear usuário", "sec_admin:unblock_user")],
        [create_button("Histórico de anti-flood", "sec_admin:history")],
        [create_button("🔙 VOLTAR", "admin:main")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


# ----------------------------------------------------------------------
# EDIÇÃO DE LIMITES
# ----------------------------------------------------------------------

async def _edit_sec_setting(callback: CallbackQuery, state: FSMContext, key: str, title: str):
    """Inicia edição de configuração de segurança."""
    await state.set_state(AdminSecurityStates.WAITING_VALUE)
    await state.update_data(sec_setting_key=key)
    text = f"Digite o novo valor para <b>{title}</b>:"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "sec_admin:main")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "sec_admin:set_msg_limit")
async def set_msg_limit(callback: CallbackQuery, state: FSMContext):
    await _edit_sec_setting(callback, state, "antiflood_msg_limit", "limite de mensagens")


@router.callback_query(F.data == "sec_admin:set_cmd_limit")
async def set_cmd_limit(callback: CallbackQuery, state: FSMContext):
    await _edit_sec_setting(callback, state, "antiflood_cmd_limit", "limite de comandos")


@router.callback_query(F.data == "sec_admin:set_callback_limit")
async def set_callback_limit(callback: CallbackQuery, state: FSMContext):
    await _edit_sec_setting(callback, state, "antiflood_callback_limit", "limite de callbacks")


@router.callback_query(F.data == "sec_admin:set_input_limit")
async def set_input_limit(callback: CallbackQuery, state: FSMContext):
    await _edit_sec_setting(callback, state, "antiflood_input_limit", "limite de inputs")


@router.callback_query(F.data == "sec_admin:set_inline_limit")
async def set_inline_limit(callback: CallbackQuery, state: FSMContext):
    await _edit_sec_setting(callback, state, "antiflood_inline_limit", "limite de inline")


@router.callback_query(F.data == "sec_admin:set_webapp_limit")
async def set_webapp_limit(callback: CallbackQuery, state: FSMContext):
    await _edit_sec_setting(callback, state, "antiflood_webapp_limit", "limite de WebApp")


@router.callback_query(F.data == "sec_admin:set_block_time")
async def set_block_time(callback: CallbackQuery, state: FSMContext):
    await _edit_sec_setting(callback, state, "antiflood_block_seconds", "tempo de bloqueio (segundos)")


@router.callback_query(F.data == "sec_admin:set_block_message")
async def set_block_message(callback: CallbackQuery, state: FSMContext):
    await _edit_sec_setting(callback, state, "antiflood_block_message", "mensagem de bloqueio")


@router.callback_query(F.data == "sec_admin:toggle_permanent_block")
async def toggle_permanent_block(callback: CallbackQuery, state: FSMContext):
    """Alterna bloqueio permanente."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return
        current = await _get_setting(session, tenant.id, "antiflood_permanent_block") or "false"
        new_val = "false" if current == "true" else "true"
        await _set_setting(session, tenant.id, "antiflood_permanent_block", new_val)

    await callback.answer(f"Bloqueio permanente {'ativado' if new_val == 'true' else 'desativado'}.")
    await security_main(callback, state)


# ----------------------------------------------------------------------
# WHITELIST E LISTA DE BLOQUEADOS
# ----------------------------------------------------------------------

@router.callback_query(F.data == "sec_admin:whitelist")
async def whitelist_menu(callback: CallbackQuery, state: FSMContext):
    """Menu de whitelist (simplificado)."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    text = "Whitelist de administradores:\n\nOs administradores são automaticamente isentos de anti-flood."
    buttons = [[create_button("🔙 VOLTAR", "sec_admin:main")]]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "sec_admin:blocked_list")
async def blocked_list(callback: CallbackQuery, state: FSMContext):
    """Lista usuários bloqueados."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        blocks = (await session.execute(
            select(UserBlock).where(
                UserBlock.tenant_id == tenant.id,
                UserBlock.is_active == True,
                UserBlock.deleted_at.is_(None),
            )
            .order_by(UserBlock.created_at.desc())
            .limit(10)
        )).scalars().all()

    if not blocks:
        text = "Nenhum usuário bloqueado."
    else:
        text = "Lista de bloqueados (últimos 10):\n\n"
        for b in blocks:
            text += f"• User ID: {b.user_id} - Motivo: {b.reason[:30]}\n"

    buttons = [[create_button("🔙 VOLTAR", "sec_admin:main")]]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "sec_admin:unblock_user")
async def unblock_user_start(callback: CallbackQuery, state: FSMContext):
    """Pede usuário para desbloquear."""
    await state.set_state(AdminSecurityStates.WAITING_USER_SEARCH)
    text = "Digite o Telegram ID ou @username do usuário para desbloquear:"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "sec_admin:main")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminSecurityStates.WAITING_USER_SEARCH)
async def process_unblock_user(message: Message, state: FSMContext):
    """Desbloqueia usuário."""
    term = message.text.strip()
    if not term:
        await message.answer("Termo vazio.")
        return

    tenant, admin = await _get_tenant_and_user_from_message(message)
    if tenant is None:
        await message.answer("Sistema indisponível.")
        await state.clear()
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, admin.id):
            await message.answer("Acesso negado.")
            await state.clear()
            return

        target = None
        if term.isdigit():
            target = (await session.execute(
                select(User).where(User.tenant_id == tenant.id, User.telegram_id == int(term))
            )).scalar_one_or_none()
        elif term.startswith("@"):
            target = (await session.execute(
                select(User).where(User.tenant_id == tenant.id, User.username == term[1:])
            )).scalar_one_or_none()

        if target is None:
            await message.answer("Usuário não encontrado.")
            await state.clear()
            return

        # Desativa bloqueios ativos
        blocks = (await session.execute(
            select(UserBlock).where(
                UserBlock.tenant_id == tenant.id,
                UserBlock.user_id == target.id,
                UserBlock.is_active == True,
            )
        )).scalars().all()
        for block in blocks:
            block.is_active = False
            block.deleted_at = datetime.now(timezone.utc)

        target.is_blocked = False
        target.block_reason = None
        await session.commit()

    await state.clear()
    await message.answer("✅ Usuário desbloqueado.")


# ----------------------------------------------------------------------
# HISTÓRICO DE ANTI-FLOOD
# ----------------------------------------------------------------------

@router.callback_query(F.data == "sec_admin:history")
async def antiflood_history(callback: CallbackQuery, state: FSMContext):
    """Exibe eventos recentes de anti-flood (se houver modelo)."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        # Busca do AuditLog ações de anti-flood
        logs = (await session.execute(
            select(AuditLog)
            .where(
                AuditLog.tenant_id == tenant.id,
                AuditLog.action.ilike("%antiflood%"),
            )
            .order_by(AuditLog.created_at.desc())
            .limit(10)
        )).scalars().all()

    if not logs:
        text = "Nenhum evento de anti-flood registrado."
    else:
        text = "Histórico de anti-flood (últimos 10):\n\n"
        for log in logs:
            text += f"{log.created_at.strftime('%d/%m/%Y %H:%M')} - {log.action}\n"

    buttons = [[create_button("🔙 VOLTAR", "sec_admin:main")]]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminSecurityStates.WAITING_VALUE)
async def process_sec_setting(message: Message, state: FSMContext):
    """Salva novo valor de configuração de segurança."""
    new_value = message.text.strip()
    if not new_value:
        await message.answer("Valor vazio não permitido.")
        return

    data = await state.get_data()
    setting_key = data.get("sec_setting_key")

    tenant, admin = await _get_tenant_and_user_from_message(message)
    if tenant is None:
        await message.answer("Sistema indisponível.")
        await state.clear()
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, admin.id):
            await message.answer("Acesso negado.")
            await state.clear()
            return
        await _set_setting(session, tenant.id, setting_key, new_value)

    await state.clear()
    await message.answer("✅ Configuração de segurança atualizada.")
