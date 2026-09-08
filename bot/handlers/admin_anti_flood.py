"""
Handlers administrativos de anti-flood e manutenção.

Permite ao administrador:
- Ativar/desativar anti-flood
- Configurar limite de ações, intervalo e tempo de bloqueio
- Ativar/desativar modo manutenção
- Alterar mensagens de manutenção

Tudo com edição da mesma mensagem e botões de voltar.
"""

import logging
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
from bot.services.user_service import get_tenant_for_bot, get_or_create_user

logger = logging.getLogger(__name__)

router = Router()


class AdminAntiFloodStates(StatesGroup):
    WAITING_MAX_ACTIONS = State()
    WAITING_WINDOW_SECONDS = State()
    WAITING_BLOCK_SECONDS = State()
    WAITING_MAINTENANCE_MESSAGE = State()
    WAITING_RETURN_MESSAGE = State()


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


async def _is_admin(session, tenant_id, user_id) -> bool:
    """Verifica se o usuário é admin/dono."""
    from bot.models.admin_user import AdminUser

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
        )
    )).scalar_one_or_none()
    return admin is not None


async def _get_setting(session, tenant_id, key: str) -> Optional[str]:
    """Busca valor de configuração."""
    stmt = select(Settings).where(
        Settings.tenant_id == tenant_id,
        Settings.key == key,
        Settings.deleted_at.is_(None),
    )
    setting = (await session.execute(stmt)).scalar_one_or_none()
    return setting.value if setting else None


async def _set_setting(session, tenant_id, key: str, value: str) -> None:
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


@router.callback_query(F.data == "admin:antiflood")
async def antiflood_menu(callback: CallbackQuery, state: FSMContext):
    """Menu de configuração de anti-flood."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        max_actions = await _get_setting(session, tenant.id, "antiflood_max_actions") or "10"
        window = await _get_setting(session, tenant.id, "antiflood_window_seconds") or "10"
        block = await _get_setting(session, tenant.id, "antiflood_block_seconds") or "60"
        enabled = await _get_setting(session, tenant.id, "antiflood_enabled") or "false"

    text = (
        "🛡 ANTI-FLOOD\n\n"
        f"Status: {'🟢 ON' if enabled == 'true' else '🔴 OFF'}\n"
        f"Limite de ações: {max_actions}\n"
        f"Intervalo (segundos): {window}\n"
        f"Tempo de bloqueio (segundos): {block}\n\n"
        "Escolha uma opção:"
    )
    buttons = [
        [create_button(
            "Desativar" if enabled == 'true' else "Ativar",
            "admin:antiflood_toggle"
        )],
        [create_button("Alterar limite de ações", "admin:antiflood_set_max")],
        [create_button("Alterar intervalo", "admin:antiflood_set_window")],
        [create_button("Alterar tempo de bloqueio", "admin:antiflood_set_block")],
        [create_button("🔙 VOLTAR", "admin:main")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "admin:antiflood_toggle")
async def antiflood_toggle(callback: CallbackQuery, state: FSMContext):
    """Alterna status do anti-flood."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        current = await _get_setting(session, tenant.id, "antiflood_enabled") or "false"
        new_value = "false" if current == "true" else "true"
        await _set_setting(session, tenant.id, "antiflood_enabled", new_value)

    await callback.answer(f"Anti-flood {'desativado' if new_value == 'false' else 'ativado'}.")
    await antiflood_menu(callback, state)


@router.callback_query(F.data == "admin:antiflood_set_max")
async def set_max_actions(callback: CallbackQuery, state: FSMContext):
    """Pede novo limite de ações."""
    await state.set_state(AdminAntiFloodStates.WAITING_MAX_ACTIONS)
    text = "Digite o novo limite de ações (ex: 10):"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "admin:antiflood")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminAntiFloodStates.WAITING_MAX_ACTIONS)
async def process_max_actions(message: Message, state: FSMContext):
    """Salva novo limite de ações."""
    value = message.text.strip()
    if not value.isdigit() or int(value) < 1:
        await message.answer("Valor inválido.")
        return

    tenant, user = await _get_tenant_and_user_from_message(message)
    if tenant is None:
        await message.answer("Sistema indisponível.")
        await state.clear()
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await message.answer("Acesso negado.")
            await state.clear()
            return
        await _set_setting(session, tenant.id, "antiflood_max_actions", value)

    await state.clear()
    await message.answer(f"✅ Limite de ações atualizado para {value}.")


@router.callback_query(F.data == "admin:antiflood_set_window")
async def set_window(callback: CallbackQuery, state: FSMContext):
    """Pede novo intervalo."""
    await state.set_state(AdminAntiFloodStates.WAITING_WINDOW_SECONDS)
    text = "Digite o novo intervalo em segundos (ex: 10):"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "admin:antiflood")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminAntiFloodStates.WAITING_WINDOW_SECONDS)
async def process_window(message: Message, state: FSMContext):
    """Salva novo intervalo."""
    value = message.text.strip()
    if not value.isdigit() or int(value) < 1:
        await message.answer("Valor inválido.")
        return

    tenant, user = await _get_tenant_and_user_from_message(message)
    if tenant is None:
        await message.answer("Sistema indisponível.")
        await state.clear()
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await message.answer("Acesso negado.")
            await state.clear()
            return
        await _set_setting(session, tenant.id, "antiflood_window_seconds", value)

    await state.clear()
    await message.answer(f"✅ Intervalo atualizado para {value} segundos.")


@router.callback_query(F.data == "admin:antiflood_set_block")
async def set_block(callback: CallbackQuery, state: FSMContext):
    """Pede novo tempo de bloqueio."""
    await state.set_state(AdminAntiFloodStates.WAITING_BLOCK_SECONDS)
    text = "Digite o novo tempo de bloqueio em segundos (0 para permanente):"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "admin:antiflood")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminAntiFloodStates.WAITING_BLOCK_SECONDS)
async def process_block(message: Message, state: FSMContext):
    """Salva novo tempo de bloqueio."""
    value = message.text.strip()
    if not value.isdigit() or int(value) < 0:
        await message.answer("Valor inválido.")
        return

    tenant, user = await _get_tenant_and_user_from_message(message)
    if tenant is None:
        await message.answer("Sistema indisponível.")
        await state.clear()
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await message.answer("Acesso negado.")
            await state.clear()
            return
        await _set_setting(session, tenant.id, "antiflood_block_seconds", value)

    await state.clear()
    await message.answer(f"✅ Tempo de bloqueio atualizado para {value} segundos.")


@router.callback_query(F.data == "admin:maintenance")
async def maintenance_menu(callback: CallbackQuery, state: FSMContext):
    """Menu de modo manutenção."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        enabled = await _get_setting(session, tenant.id, "maintenance_mode") or "false"
        maint_msg = await _get_setting(session, tenant.id, "maintenance_message") or (
            "🔧 BOT EM MANUTENÇÃO\nEstamos realizando uma manutenção.\nTente novamente mais tarde."
        )
        return_msg = await _get_setting(session, tenant.id, "maintenance_return_message") or (
            "🟢 BOT ONLINE\nA manutenção foi finalizada.\nO bot já está funcionando normalmente!"
        )

    text = (
        "🔧 MANUTENÇÃO\n\n"
        f"Status: {'🟢 ON' if enabled == 'true' else '🔴 OFF'}\n\n"
        "Opções:"
    )
    buttons = [
        [create_button(
            "Desativar" if enabled == 'true' else "Ativar",
            "admin:maintenance_toggle"
        )],
        [create_button("Alterar mensagem de manutenção", "admin:maintenance_message")],
        [create_button("Alterar mensagem de retorno", "admin:maintenance_return")],
        [create_button("🔙 VOLTAR", "admin:main")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "admin:maintenance_toggle")
async def maintenance_toggle(callback: CallbackQuery, state: FSMContext):
    """Alterna modo manutenção."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        current = await _get_setting(session, tenant.id, "maintenance_mode") or "false"
        new_value = "false" if current == "true" else "true"
        await _set_setting(session, tenant.id, "maintenance_mode", new_value)

    await callback.answer(f"Modo manutenção {'desativado' if new_value == 'false' else 'ativado'}.")
    await maintenance_menu(callback, state)


@router.callback_query(F.data == "admin:maintenance_message")
async def edit_maintenance_message(callback: CallbackQuery, state: FSMContext):
    """Pede nova mensagem de manutenção."""
    await state.set_state(AdminAntiFloodStates.WAITING_MAINTENANCE_MESSAGE)
    text = "Digite a nova mensagem de manutenção:"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "admin:maintenance")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminAntiFloodStates.WAITING_MAINTENANCE_MESSAGE)
async def process_maintenance_message(message: Message, state: FSMContext):
    """Salva nova mensagem de manutenção."""
    new_msg = message.text.strip() if message.text else ""
    if not new_msg:
        await message.answer("Mensagem vazia.")
        return

    tenant, user = await _get_tenant_and_user_from_message(message)
    if tenant is None:
        await message.answer("Sistema indisponível.")
        await state.clear()
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await message.answer("Acesso negado.")
            await state.clear()
            return
        await _set_setting(session, tenant.id, "maintenance_message", new_msg)

    await state.clear()
    await message.answer("✅ Mensagem de manutenção atualizada.")


@router.callback_query(F.data == "admin:maintenance_return")
async def edit_return_message(callback: CallbackQuery, state: FSMContext):
    """Pede nova mensagem de retorno."""
    await state.set_state(AdminAntiFloodStates.WAITING_RETURN_MESSAGE)
    text = "Digite a nova mensagem de retorno (quando manutenção terminar):"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "admin:maintenance")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminAntiFloodStates.WAITING_RETURN_MESSAGE)
async def process_return_message(message: Message, state: FSMContext):
    """Salva nova mensagem de retorno."""
    new_msg = message.text.strip() if message.text else ""
    if not new_msg:
        await message.answer("Mensagem vazia.")
        return

    tenant, user = await _get_tenant_and_user_from_message(message)
    if tenant is None:
        await message.answer("Sistema indisponível.")
        await state.clear()
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await message.answer("Acesso negado.")
            await state.clear()
            return
        await _set_setting(session, tenant.id, "maintenance_return_message", new_msg)

    await state.clear()
    await message.answer("✅ Mensagem de retorno atualizada.")
