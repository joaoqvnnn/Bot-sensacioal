"""
Handlers administrativos de Carteira/Saldo.

Seção 15 do painel: gerencia saldo e ledger de usuários.
Permite consultar saldo, extrato, crédito/débito manual com motivo
obrigatório, e visualizar histórico de movimentações.

Toda alteração de saldo gera ledger + auditoria.
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
from bot.models.user import User
from bot.models.wallet import Wallet, WalletLedger
from bot.services.user_service import get_tenant_for_bot, get_or_create_user
from bot.services.wallet_service import get_balance, credit_wallet, debit_wallet
from bot.services.audit_service import audit_log

logger = logging.getLogger(__name__)

router = Router()


class AdminWalletStates(StatesGroup):
    WAITING_USER_SEARCH = State()
    WAITING_CREDIT_AMOUNT = State()
    WAITING_DEBIT_AMOUNT = State()
    WAITING_REASON = State()


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


async def _edit_or_answer(callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup):
    """Edita a mensagem atual, se possível."""
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "wallet_admin:main")
async def wallet_admin_main(callback: CallbackQuery, state: FSMContext):
    """Menu principal de carteira/saldo."""
    await state.set_state(AdminWalletStates.WAITING_USER_SEARCH)
    text = "Digite o Telegram ID, @username, WhatsApp ou e-mail do usuário:"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "admin:main")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminWalletStates.WAITING_USER_SEARCH)
async def process_user_search(message: Message, state: FSMContext):
    """Busca usuário e exibe saldo/opções."""
    term = message.text.strip() if message.text else ""
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
        else:
            target = (await session.execute(
                select(User).where(
                    User.tenant_id == tenant.id,
                    ((User.whatsapp == term) | (User.email == term))
                )
            )).scalar_one_or_none()

        if target is None:
            await message.answer("Usuário não encontrado.")
            await state.clear()
            return

        balance_cents = await get_balance(session, tenant.id, target.id)

    text = (
        f"👤 Usuário: {target.first_name or target.username} (ID: {target.telegram_id})\n"
        f"💰 Saldo: {cents_to_brl(balance_cents)}\n\n"
        "Escolha uma ação:"
    )
    buttons = [
        [create_button("➕ Crédito manual", f"wallet_admin:credit:{target.id}")],
        [create_button("➖ Débito manual", f"wallet_admin:debit:{target.id}")],
        [create_button("📋 Extrato", f"wallet_admin:ledger:{target.id}")],
        [create_button("🔙 VOLTAR", "admin:main")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(text, reply_markup=keyboard)
    await state.clear()


@router.callback_query(F.data.startswith("wallet_admin:credit:"))
async def credit_user_start(callback: CallbackQuery, state: FSMContext):
    """Pede valor para crédito."""
    user_id = UUID(callback.data.split(":")[-1])
    await state.update_data(target_user_id=str(user_id), operation="credit")
    await state.set_state(AdminWalletStates.WAITING_CREDIT_AMOUNT)
    text = "Digite o valor a creditar (ex: 10.00):"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "wallet_admin:main")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data.startswith("wallet_admin:debit:"))
async def debit_user_start(callback: CallbackQuery, state: FSMContext):
    """Pede valor para débito."""
    user_id = UUID(callback.data.split(":")[-1])
    await state.update_data(target_user_id=str(user_id), operation="debit")
    await state.set_state(AdminWalletStates.WAITING_DEBIT_AMOUNT)
    text = "Digite o valor a debitar (ex: 5.00):"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "wallet_admin:main")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminWalletStates.WAITING_CREDIT_AMOUNT)
@router.message(AdminWalletStates.WAITING_DEBIT_AMOUNT)
async def process_manual_amount(message: Message, state: FSMContext):
    """Recebe valor e pede motivo."""
    try:
        amount_cents = int(float(message.text.strip().replace(",", ".")) * 100)
        if amount_cents <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Valor inválido.")
        return

    data = await state.get_data()
    operation = data.get("operation")

    await state.update_data(amount_cents=amount_cents)
    await state.set_state(AdminWalletStates.WAITING_REASON)
    await message.answer("Digite o motivo da alteração (obrigatório):")


@router.message(AdminWalletStates.WAITING_REASON)
async def process_manual_reason(message: Message, state: FSMContext):
    """Recebe motivo e efetua crédito/débito com ledger e auditoria."""
    reason = message.text.strip() if message.text else ""
    if not reason:
        await message.answer("Motivo obrigatório.")
        return

    data = await state.get_data()
    target_user_id = UUID(data["target_user_id"])
    operation = data["operation"]
    amount_cents = data["amount_cents"]

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

        try:
            if operation == "credit":
                await credit_wallet(
                    session,
                    tenant_id=tenant.id,
                    user_id=target_user_id,
                    amount_cents=amount_cents,
                    entry_type="adjustment",
                    description=f"Crédito manual: {reason}",
                )
                action = "creditado"
            else:
                await debit_wallet(
                    session,
                    tenant_id=tenant.id,
                    user_id=target_user_id,
                    amount_cents=amount_cents,
                    entry_type="adjustment",
                    description=f"Débito manual: {reason}",
                )
                action = "debitado"
        except ValueError as e:
            await message.answer(f"❌ {e}")
            await state.clear()
            return

        # Registra auditoria
        await audit_log(
            session,
            tenant_id=tenant.id,
            action="wallet.manual_adjustment",
            description=f"{action.capitalize()} {cents_to_brl(amount_cents)} - {reason}",
            actor_user_id=admin.id,
            target_user_id=target_user_id,
        )

    await state.clear()
    await message.answer(f"✅ Valor {action} com sucesso: {cents_to_brl(amount_cents)}")


@router.callback_query(F.data.startswith("wallet_admin:ledger:"))
async def show_ledger(callback: CallbackQuery, state: FSMContext):
    """Exibe extrato do ledger do usuário (últimas 10 movimentações)."""
    user_id = UUID(callback.data.split(":")[-1])
    tenant, admin = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, admin.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        entries = (await session.execute(
            select(WalletLedger)
            .where(
                WalletLedger.tenant_id == tenant.id,
                WalletLedger.user_id == user_id,
                WalletLedger.deleted_at.is_(None),
            )
            .order_by(WalletLedger.created_at.desc())
            .limit(10)
        )).scalars().all()

    if not entries:
        text = "Nenhuma movimentação."
    else:
        text = "📋 Extrato (últimas 10):\n\n"
        for e in entries:
            sign = "+" if int(e.amount_cents) > 0 else ""
            text += f"{e.created_at.strftime('%d/%m/%Y %H:%M')} - {e.entry_type} {sign}{cents_to_brl(int(e.amount_cents))}\n"

    buttons = [[create_button("🔙 VOLTAR", "wallet_admin:main")]]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)
