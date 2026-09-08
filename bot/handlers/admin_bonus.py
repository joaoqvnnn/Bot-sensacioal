"""
Handlers administrativos de Bônus de Registro.

Seção 7 do painel: permite configurar bônus concedido a novos usuários.
Inclui ativar/desativar, valor, público elegível, limites, data início/término
e prevenção de duplicidade. Tudo persistido na tabela Settings.
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
from bot.services.user_service import get_tenant_for_bot, get_or_create_user

logger = logging.getLogger(__name__)

router = Router()


class AdminBonusStates(StatesGroup):
    WAITING_BONUS_AMOUNT = State()
    WAITING_BONUS_ELIGIBLE = State()
    WAITING_BONUS_START = State()
    WAITING_BONUS_END = State()


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
    """Busca valor de configuração por chave."""
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


@router.callback_query(F.data == "admin:bonus")
async def show_bonus_settings(callback: CallbackQuery, state: FSMContext):
    """Exibe menu de configuração de bônus de registro."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        bonus_enabled = await _get_setting(session, tenant.id, "registration_bonus_enabled") or "false"
        bonus_amount = await _get_setting(session, tenant.id, "registration_bonus_amount_cents") or "0"
        eligible = await _get_setting(session, tenant.id, "registration_bonus_eligible") or "all"
        start_date = await _get_setting(session, tenant.id, "registration_bonus_start") or ""
        end_date = await _get_setting(session, tenant.id, "registration_bonus_end") or ""

    text = (
        "🎁 BÔNUS DE REGISTRO\n\n"
        f"Status: {'🟢 ON' if bonus_enabled == 'true' else '🔴 OFF'}\n"
        f"Valor: R$ {int(bonus_amount)/100:.2f}\n"
        f"Público elegível: {eligible}\n"
        f"Data início: {start_date or 'Sem início'}\n"
        f"Data término: {end_date or 'Sem término'}\n\n"
        "Escolha uma opção:"
    )
    buttons = [
        [create_button(
            "Desativar" if bonus_enabled == 'true' else "Ativar",
            "bonus:toggle"
        )],
        [create_button("💰 Alterar valor", "bonus:set_amount")],
        [create_button("👥 Alterar público", "bonus:set_eligible")],
        [create_button("📅 Data início", "bonus:set_start")],
        [create_button("📅 Data término", "bonus:set_end")],
        [create_button("🔙 VOLTAR", "admin:main")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "bonus:toggle")
async def toggle_bonus(callback: CallbackQuery, state: FSMContext):
    """Alterna status do bônus de registro."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        current = await _get_setting(session, tenant.id, "registration_bonus_enabled") or "false"
        new_val = "false" if current == "true" else "true"
        await _set_setting(session, tenant.id, "registration_bonus_enabled", new_val)

    await callback.answer(f"Bônus de registro {'ativado' if new_val == 'true' else 'desativado'}.")
    await show_bonus_settings(callback, state)


@router.callback_query(F.data == "bonus:set_amount")
async def set_bonus_amount(callback: CallbackQuery, state: FSMContext):
    """Pede novo valor do bônus."""
    await state.set_state(AdminBonusStates.WAITING_BONUS_AMOUNT)
    text = "Digite o valor do bônus em reais (ex: 5.00):"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "admin:bonus")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminBonusStates.WAITING_BONUS_AMOUNT)
async def process_bonus_amount(message: Message, state: FSMContext):
    """Salva novo valor."""
    try:
        amount_cents = int(float(message.text.strip().replace(",", ".")) * 100)
        if amount_cents < 0:
            raise ValueError
    except ValueError:
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
        await _set_setting(session, tenant.id, "registration_bonus_amount_cents", str(amount_cents))

    await state.clear()
    await message.answer(f"✅ Bônus definido para R$ {amount_cents/100:.2f}.")


@router.callback_query(F.data == "bonus:set_eligible")
async def set_bonus_eligible(callback: CallbackQuery, state: FSMContext):
    """Pede público elegível (all, invited, etc.)."""
    await state.set_state(AdminBonusStates.WAITING_BONUS_ELIGIBLE)
    text = "Digite o público elegível (ex: all, invited, referral):"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "admin:bonus")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminBonusStates.WAITING_BONUS_ELIGIBLE)
async def process_bonus_eligible(message: Message, state: FSMContext):
    """Salva público elegível."""
    eligible = message.text.strip().lower()
    if eligible not in ("all", "invited", "referral"):
        await message.answer("Público inválido. Use all, invited ou referral.")
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
        await _set_setting(session, tenant.id, "registration_bonus_eligible", eligible)

    await state.clear()
    await message.answer(f"✅ Público elegível definido como '{eligible}'.")


@router.callback_query(F.data == "bonus:set_start")
async def set_bonus_start(callback: CallbackQuery, state: FSMContext):
    """Pede data de início."""
    await state.set_state(AdminBonusStates.WAITING_BONUS_START)
    text = "Digite a data de início (DD/MM/AAAA) ou '0' para sem data:"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "admin:bonus")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminBonusStates.WAITING_BONUS_START)
async def process_bonus_start(message: Message, state: FSMContext):
    """Salva data de início."""
    value = message.text.strip()
    if value == "0":
        date_str = ""
    else:
        try:
            datetime.strptime(value, "%d/%m/%Y")
            date_str = value
        except ValueError:
            await message.answer("Data inválida. Use DD/MM/AAAA.")
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
        await _set_setting(session, tenant.id, "registration_bonus_start", date_str)

    await state.clear()
    await message.answer("✅ Data de início atualizada.")


@router.callback_query(F.data == "bonus:set_end")
async def set_bonus_end(callback: CallbackQuery, state: FSMContext):
    """Pede data de término."""
    await state.set_state(AdminBonusStates.WAITING_BONUS_END)
    text = "Digite a data de término (DD/MM/AAAA) ou '0' para sem data:"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "admin:bonus")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminBonusStates.WAITING_BONUS_END)
async def process_bonus_end(message: Message, state: FSMContext):
    """Salva data de término."""
    value = message.text.strip()
    if value == "0":
        date_str = ""
    else:
        try:
            datetime.strptime(value, "%d/%m/%Y")
            date_str = value
        except ValueError:
            await message.answer("Data inválida. Use DD/MM/AAAA.")
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
        await _set_setting(session, tenant.id, "registration_bonus_end", date_str)

    await state.clear()
    await message.answer("✅ Data de término atualizada.")
