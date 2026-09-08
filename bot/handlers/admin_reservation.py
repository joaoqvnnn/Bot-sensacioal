"""
Handlers administrativos de Reserva de Estoque.

Seção 13 do painel: configura a reserva temporária de estoque.
Permite ativar/desativar, definir tempo de reserva, limite por usuário
e visualizar histórico de reservas ativas/expiradas.
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, func

from bot.core.database import get_async_session_factory
from bot.keyboards.utils import create_button
from bot.models.settings import Settings
from bot.models.inventory_item import InventoryItem
from bot.models.user import User
from bot.services.user_service import get_tenant_for_bot, get_or_create_user

logger = logging.getLogger(__name__)

router = Router()


class AdminReservationStates(StatesGroup):
    WAITING_TIME = State()
    WAITING_LIMIT = State()


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


@router.callback_query(F.data == "reservation:main")
async def reservation_main(callback: CallbackQuery, state: FSMContext):
    """Menu principal de reserva de estoque."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        enabled = await _get_setting(session, tenant.id, "reservation_enabled") or "true"
        time_minutes = await _get_setting(session, tenant.id, "reservation_minutes") or "10"
        per_user_limit = await _get_setting(session, tenant.id, "reservation_per_user_limit") or "5"

        # Contagens
        active_reservations = (await session.execute(
            select(func.count(InventoryItem.id)).where(
                InventoryItem.tenant_id == tenant.id,
                InventoryItem.status == "RESERVED",
                InventoryItem.deleted_at.is_(None),
            )
        )).scalar_one()

    text = (
        "🔒 RESERVA DE ESTOQUE\n\n"
        f"Status: {'🟢 ON' if enabled == 'true' else '🔴 OFF'}\n"
        f"Tempo de reserva: {time_minutes} min\n"
        f"Limite por usuário: {per_user_limit} itens\n"
        f"Reservas ativas: {active_reservations}\n\n"
        "Escolha uma opção:"
    )
    buttons = [
        [create_button(
            "Desativar" if enabled == 'true' else "Ativar",
            "reservation:toggle"
        )],
        [create_button("⏱ Alterar tempo", "reservation:set_time")],
        [create_button("👤 Alterar limite por usuário", "reservation:set_limit")],
        [create_button("📋 Ver reservas ativas", "reservation:active_list")],
        [create_button("🔙 VOLTAR", "admin:main")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "reservation:toggle")
async def reservation_toggle(callback: CallbackQuery, state: FSMContext):
    """Alterna status da reserva."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        current = await _get_setting(session, tenant.id, "reservation_enabled") or "true"
        new_val = "false" if current == "true" else "true"
        await _set_setting(session, tenant.id, "reservation_enabled", new_val)

    await callback.answer(f"Reserva {'desativada' if new_val == 'false' else 'ativada'}.")
    await reservation_main(callback, state)


@router.callback_query(F.data == "reservation:set_time")
async def reservation_set_time(callback: CallbackQuery, state: FSMContext):
    """Pede novo tempo de reserva."""
    await state.set_state(AdminReservationStates.WAITING_TIME)
    text = "Digite o tempo de reserva em minutos (ex: 10):"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "reservation:main")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminReservationStates.WAITING_TIME)
async def process_reservation_time(message: Message, state: FSMContext):
    """Salva novo tempo de reserva."""
    time_str = message.text.strip()
    if not time_str.isdigit() or int(time_str) < 1:
        await message.answer("Valor inválido.")
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
        await _set_setting(session, tenant.id, "reservation_minutes", time_str)

    await state.clear()
    await message.answer(f"✅ Tempo de reserva atualizado para {time_str} minutos.")


@router.callback_query(F.data == "reservation:set_limit")
async def reservation_set_limit(callback: CallbackQuery, state: FSMContext):
    """Pede novo limite por usuário."""
    await state.set_state(AdminReservationStates.WAITING_LIMIT)
    text = "Digite o limite de itens por usuário (ex: 5):"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "reservation:main")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminReservationStates.WAITING_LIMIT)
async def process_reservation_limit(message: Message, state: FSMContext):
    """Salva novo limite por usuário."""
    limit_str = message.text.strip()
    if not limit_str.isdigit() or int(limit_str) < 1:
        await message.answer("Valor inválido.")
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
        await _set_setting(session, tenant.id, "reservation_per_user_limit", limit_str)

    await state.clear()
    await message.answer(f"✅ Limite por usuário atualizado para {limit_str} itens.")


@router.callback_query(F.data == "reservation:active_list")
async def reservation_active_list(callback: CallbackQuery, state: FSMContext):
    """Lista reservas ativas resumidas."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        items = (await session.execute(
            select(InventoryItem).where(
                InventoryItem.tenant_id == tenant.id,
                InventoryItem.status == "RESERVED",
                InventoryItem.deleted_at.is_(None),
            )
        )).scalars().all()

    if not items:
        text = "Nenhuma reserva ativa."
    else:
        text = "📋 Reservas ativas:\n\n"
        for item in items:
            text += f"• Produto ID: {item.product_id} - Expira em: {item.reservation_expires_at.strftime('%d/%m/%Y %H:%M')}\n"

    buttons = [[create_button("🔙 VOLTAR", "reservation:main")]]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)
