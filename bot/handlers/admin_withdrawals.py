"""
Handlers administrativos de Saques.

Seção 17 do painel: gerencia solicitações de saque.
Permite configurar ON/OFF, valor mínimo/máximo, processamento automático/manual,
limites diários, e aprovar/reprovar saques pendentes.
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
from bot.core.utils import cents_to_brl
from bot.keyboards.utils import create_button
from bot.models.settings import Settings
from bot.models.withdrawal import Withdrawal
from bot.models.user import User
from bot.services.user_service import get_tenant_for_bot, get_or_create_user
from bot.services.withdrawal_service import process_withdrawal_status

logger = logging.getLogger(__name__)

router = Router()


class AdminWithdrawalsStates(StatesGroup):
    WAITING_MIN = State()
    WAITING_MAX = State()
    WAITING_DAILY_LIMIT = State()


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


@router.callback_query(F.data == "withdrawals_admin:main")
async def withdrawals_main(callback: CallbackQuery, state: FSMContext):
    """Menu principal de saques."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        enabled = await _get_setting(session, tenant.id, "withdrawal_enabled") or "true"
        min_value = await _get_setting(session, tenant.id, "withdrawal_min") or "20.00"
        max_value = await _get_setting(session, tenant.id, "withdrawal_max") or "1000.00"
        daily_limit = await _get_setting(session, tenant.id, "withdrawal_daily_limit") or "2000.00"
        auto_process = await _get_setting(session, tenant.id, "withdrawal_auto_process") or "false"

        pending = (await session.execute(
            select(func.count(Withdrawal.id)).where(
                Withdrawal.tenant_id == tenant.id,
                Withdrawal.status == "PENDING",
                Withdrawal.deleted_at.is_(None),
            )
        )).scalar_one()
        processing = (await session.execute(
            select(func.count(Withdrawal.id)).where(
                Withdrawal.tenant_id == tenant.id,
                Withdrawal.status == "PROCESSING",
                Withdrawal.deleted_at.is_(None),
            )
        )).scalar_one()

    text = (
        "💸 SAQUES\n\n"
        f"Status: {'🟢 ON' if enabled == 'true' else '🔴 OFF'}\n"
        f"Valor mínimo: R$ {min_value}\n"
        f"Valor máximo: R$ {max_value}\n"
        f"Limite diário: R$ {daily_limit}\n"
        f"Processamento automático: {'Sim' if auto_process == 'true' else 'Não'}\n"
        f"Pendentes: {pending}\n"
        f"Processando: {processing}\n\n"
        "Escolha uma opção:"
    )
    buttons = [
        [create_button("Ativar/Desativar", "withdrawals_admin:toggle")],
        [create_button("Alterar valor mínimo", "withdrawals_admin:set_min")],
        [create_button("Alterar valor máximo", "withdrawals_admin:set_max")],
        [create_button("Alterar limite diário", "withdrawals_admin:set_daily_limit")],
        [create_button("Processamento automático", "withdrawals_admin:toggle_auto")],
        [create_button("📋 Ver pendentes", "withdrawals_admin:pending_list")],
        [create_button("📋 Histórico", "withdrawals_admin:history")],
        [create_button("🔙 VOLTAR", "admin:main")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "withdrawals_admin:toggle")
async def toggle_withdrawals(callback: CallbackQuery, state: FSMContext):
    """Alterna sistema de saques."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return
        current = await _get_setting(session, tenant.id, "withdrawal_enabled") or "true"
        new_val = "false" if current == "true" else "true"
        await _set_setting(session, tenant.id, "withdrawal_enabled", new_val)

    await callback.answer(f"Saques {'ativados' if new_val == 'true' else 'desativados'}.")
    await withdrawals_main(callback, state)


@router.callback_query(F.data == "withdrawals_admin:toggle_auto")
async def toggle_auto_process(callback: CallbackQuery, state: FSMContext):
    """Alterna processamento automático."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return
        current = await _get_setting(session, tenant.id, "withdrawal_auto_process") or "false"
        new_val = "false" if current == "true" else "true"
        await _set_setting(session, tenant.id, "withdrawal_auto_process", new_val)

    await callback.answer(f"Processamento automático {'ativado' if new_val == 'true' else 'desativado'}.")
    await withdrawals_main(callback, state)


@router.callback_query(F.data == "withdrawals_admin:set_min")
async def set_min(callback: CallbackQuery, state: FSMContext):
    """Pede novo valor mínimo."""
    await state.set_state(AdminWithdrawalsStates.WAITING_MIN)
    text = "Digite o valor mínimo de saque (ex: 20.00):"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "withdrawals_admin:main")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminWithdrawalsStates.WAITING_MIN)
async def process_min(message: Message, state: FSMContext):
    """Salva novo mínimo."""
    try:
        value = float(message.text.strip().replace(",", "."))
        if value <= 0:
            raise ValueError
    except ValueError:
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
        await _set_setting(session, tenant.id, "withdrawal_min", f"{value:.2f}")

    await state.clear()
    await message.answer(f"✅ Valor mínimo atualizado para R$ {value:.2f}.")


@router.callback_query(F.data == "withdrawals_admin:set_max")
async def set_max(callback: CallbackQuery, state: FSMContext):
    """Pede novo valor máximo."""
    await state.set_state(AdminWithdrawalsStates.WAITING_MAX)
    text = "Digite o valor máximo de saque (ex: 1000.00):"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "withdrawals_admin:main")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminWithdrawalsStates.WAITING_MAX)
async def process_max(message: Message, state: FSMContext):
    """Salva novo máximo."""
    try:
        value = float(message.text.strip().replace(",", "."))
        if value <= 0:
            raise ValueError
    except ValueError:
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
        await _set_setting(session, tenant.id, "withdrawal_max", f"{value:.2f}")

    await state.clear()
    await message.answer(f"✅ Valor máximo atualizado para R$ {value:.2f}.")


@router.callback_query(F.data == "withdrawals_admin:set_daily_limit")
async def set_daily_limit(callback: CallbackQuery, state: FSMContext):
    """Pede novo limite diário."""
    await state.set_state(AdminWithdrawalsStates.WAITING_DAILY_LIMIT)
    text = "Digite o limite diário de saques (ex: 2000.00):"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "withdrawals_admin:main")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminWithdrawalsStates.WAITING_DAILY_LIMIT)
async def process_daily_limit(message: Message, state: FSMContext):
    """Salva novo limite diário."""
    try:
        value = float(message.text.strip().replace(",", "."))
        if value <= 0:
            raise ValueError
    except ValueError:
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
        await _set_setting(session, tenant.id, "withdrawal_daily_limit", f"{value:.2f}")

    await state.clear()
    await message.answer(f"✅ Limite diário atualizado para R$ {value:.2f}.")


# ----------------------------------------------------------------------
# LISTAGEM DE PENDENTES E APROVAÇÃO
# ----------------------------------------------------------------------

@router.callback_query(F.data == "withdrawals_admin:pending_list")
async def pending_list(callback: CallbackQuery, state: FSMContext):
    """Lista saques pendentes com opção de aprovar/reprovar."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        pending = (await session.execute(
            select(Withdrawal)
            .where(
                Withdrawal.tenant_id == tenant.id,
                Withdrawal.status == "PENDING",
                Withdrawal.deleted_at.is_(None),
            )
            .order_by(Withdrawal.created_at.asc())
            .limit(10)
        )).scalars().all()

    if not pending:
        text = "Nenhum saque pendente."
    else:
        text = "💸 Saques pendentes:\n\n"
        for w in pending:
            text += (
                f"ID: {w.id}\n"
                f"Valor: {cents_to_brl(int(w.amount_cents))}\n"
                f"Data: {w.created_at.strftime('%d/%m/%Y %H:%M')}\n"
                f"Conta: {w.withdrawal_account_id}\n"
                "--------------------------\n"
            )

    buttons = []
    for w in pending:
        buttons.append([create_button(f"✅ Aprovar {cents_to_brl(int(w.amount_cents))}", f"withdrawals_admin:approve:{w.id}")])
        buttons.append([create_button(f"❌ Reprovar {cents_to_brl(int(w.amount_cents))}", f"withdrawals_admin:reject:{w.id}")])
    buttons.append([create_button("🔙 VOLTAR", "withdrawals_admin:main")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data.startswith("withdrawals_admin:approve:"))
async def approve_withdrawal(callback: CallbackQuery, state: FSMContext):
    """Aprova um saque pendente."""
    withdrawal_id = UUID(callback.data.split(":")[-1])
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        await process_withdrawal_status(
            session=session,
            tenant_id=tenant.id,
            withdrawal_id=withdrawal_id,
            new_status="PAID",
        )

    await callback.answer("Saque aprovado.")
    await pending_list(callback, state)


@router.callback_query(F.data.startswith("withdrawals_admin:reject:"))
async def reject_withdrawal(callback: CallbackQuery, state: FSMContext):
    """Reprova um saque pendente, estornando o valor."""
    withdrawal_id = UUID(callback.data.split(":")[-1])
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        await process_withdrawal_status(
            session=session,
            tenant_id=tenant.id,
            withdrawal_id=withdrawal_id,
            new_status="FAILED",
        )

    await callback.answer("Saque reprovado e valor estornado.")
    await pending_list(callback, state)


@router.callback_query(F.data == "withdrawals_admin:history")
async def withdrawals_history(callback: CallbackQuery, state: FSMContext):
    """Exibe histórico de saques recentes."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        withdrawals = (await session.execute(
            select(Withdrawal)
            .where(Withdrawal.tenant_id == tenant.id)
            .order_by(Withdrawal.created_at.desc())
            .limit(10)
        )).scalars().all()

    if not withdrawals:
        text = "Nenhum saque registrado."
    else:
        text = "💸 Histórico de saques:\n\n"
        for w in withdrawals:
            text += (
                f"{w.created_at.strftime('%d/%m/%Y %H:%M')} - "
                f"{cents_to_brl(int(w.amount_cents))} - {w.status}\n"
            )

    buttons = [[create_button("🔙 VOLTAR", "withdrawals_admin:main")]]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)
