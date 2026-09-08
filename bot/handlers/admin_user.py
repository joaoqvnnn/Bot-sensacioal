"""
Handlers administrativos de usuários.

Permite ao administrador:
- Pesquisar usuário por Telegram ID, username, WhatsApp ou e-mail
- Visualizar dados do usuário (saldo, compras, status)
- Alterar saldo (com registro em ledger)
- Bloquear/desbloquear usuário
- Listar usuários recentes

Tudo com edição da mesma mensagem e botões de voltar.
"""

import logging
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
from bot.models.tenant import Tenant
from bot.models.wallet import Wallet
from bot.models.order import Order
from bot.services.user_service import get_tenant_for_bot, get_or_create_user
from bot.services.wallet_service import credit_wallet, debit_wallet

logger = logging.getLogger(__name__)

router = Router()


class AdminUserStates(StatesGroup):
    WAITING_SEARCH_TERM = State()
    WAITING_ADJUST_AMOUNT = State()
    WAITING_BLOCK_REASON = State()


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


async def _edit_or_answer(callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup):
    """Edita a mensagem atual, se possível."""
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "admin:manage_users")
async def manage_users(callback: CallbackQuery, state: FSMContext):
    """Menu de gerenciamento de usuários."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        total_users = (await session.execute(
            select(func.count(User.id)).where(
                User.tenant_id == tenant.id,
                User.deleted_at.is_(None),
            )
        )).scalar_one()

    text = (
        "👥 CONFIGURAR USUÁRIOS\n\n"
        f"Total de usuários: {total_users}\n\n"
        "Opções:"
    )
    buttons = [
        [create_button("🔎 PESQUISAR USUÁRIO", "admin:search_user")],
        [create_button("📢 TRANSMITIR A TODOS", "admin:broadcast")],
        [create_button("🎁 BÔNUS DE REGISTRO", "admin:registration_bonus")],
        [create_button("🔙 VOLTAR", "admin:main")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "admin:search_user")
async def search_user(callback: CallbackQuery, state: FSMContext):
    """Pede termo de busca."""
    await state.set_state(AdminUserStates.WAITING_SEARCH_TERM)
    text = (
        "Digite o termo de busca:\n"
        "- Telegram ID\n"
        "- @username\n"
        "- WhatsApp\n"
        "- E-mail"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "admin:manage_users")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminUserStates.WAITING_SEARCH_TERM)
async def process_search_user(message: Message, state: FSMContext):
    """Busca usuário e exibe resultado."""
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

        user = None
        if term.isdigit():
            user = (await session.execute(
                select(User).where(
                    User.tenant_id == tenant.id,
                    User.telegram_id == int(term),
                    User.deleted_at.is_(None),
                )
            )).scalar_one_or_none()
        elif term.startswith("@"):
            user = (await session.execute(
                select(User).where(
                    User.tenant_id == tenant.id,
                    User.username == term[1:],
                    User.deleted_at.is_(None),
                )
            )).scalar_one_or_none()
        else:
            # busca por whatsapp ou email
            user = (await session.execute(
                select(User).where(
                    User.tenant_id == tenant.id,
                    (
                        (User.whatsapp == term) |
                        (User.email == term)
                    ),
                    User.deleted_at.is_(None),
                )
            )).scalar_one_or_none()

        if user is None:
            await message.answer("Usuário não encontrado.")
            await state.clear()
            return

        balance_cents = 0
        wallet = (await session.execute(
            select(Wallet).where(Wallet.user_id == user.id, Wallet.tenant_id == tenant.id)
        )).scalar_one_or_none()
        if wallet:
            balance_cents = int(wallet.balance_cents)

        total_orders = (await session.execute(
            select(func.count(Order.id)).where(
                Order.tenant_id == tenant.id,
                Order.user_id == user.id,
                Order.status == "COMPLETED",
                Order.deleted_at.is_(None),
            )
        )).scalar_one()

    text = (
        "👤 Usuário encontrado:\n\n"
        f"🆔 ID: {user.telegram_id}\n"
        f"👤 Nome: {user.first_name or ''} {user.last_name or ''}\n"
        f"📱 Username: @{user.username or 'N/A'}\n"
        f"📲 WhatsApp: {user.whatsapp or 'N/A'}\n"
        f"📧 Email: {user.email or 'N/A'}\n"
        f"💰 Saldo: {cents_to_brl(balance_cents)}\n"
        f"🛒 Compras: {total_orders}\n"
        f"🚫 Bloqueado: {'Sim' if user.is_blocked else 'Não'}\n"
    )
    buttons = [
        [create_button("💰 ALTERAR SALDO", f"admin:adjust_balance:{user.id}")],
        [create_button("🚫 BLOQUEAR", f"admin:block_user:{user.id}") if not user.is_blocked else create_button("✅ DESBLOQUEAR", f"admin:unblock_user:{user.id}")],
        [create_button("🔙 VOLTAR", "admin:manage_users")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(text, reply_markup=keyboard)
    await state.clear()


@router.callback_query(F.data.startswith("admin:adjust_balance:"))
async def adjust_balance(callback: CallbackQuery, state: FSMContext):
    """Pede valor para ajuste de saldo."""
    user_id = callback.data.split(":")[-1]
    await state.update_data(adjust_user_id=user_id)
    await state.set_state(AdminUserStates.WAITING_ADJUST_AMOUNT)
    text = "Digite o valor do ajuste (ex: 10.00 para creditar, -5.00 para debitar):"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "admin:manage_users")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminUserStates.WAITING_ADJUST_AMOUNT)
async def process_adjust_balance(message: Message, state: FSMContext):
    """Processa ajuste de saldo via ledger."""
    try:
        amount_cents = int(float(message.text.replace(",", ".")) * 100)
    except ValueError:
        await message.answer("Valor inválido.")
        return

    data = await state.get_data()
    user_id = UUID(data["adjust_user_id"])

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

        if amount_cents > 0:
            await credit_wallet(
                session,
                tenant_id=tenant.id,
                user_id=user_id,
                amount_cents=amount_cents,
                entry_type="adjustment",
                description="Ajuste administrativo",
                reference_id=None,
            )
        elif amount_cents < 0:
            try:
                await debit_wallet(
                    session,
                    tenant_id=tenant.id,
                    user_id=user_id,
                    amount_cents=abs(amount_cents),
                    entry_type="adjustment",
                    description="Ajuste administrativo",
                    reference_id=None,
                )
            except ValueError as e:
                await message.answer(f"❌ {e}")
                await state.clear()
                return

    await state.clear()
    await message.answer(f"✅ Saldo ajustado em {cents_to_brl(amount_cents)}.")


@router.callback_query(F.data.startswith("admin:block_user:"))
async def block_user(callback: CallbackQuery, state: FSMContext):
    """Bloqueia usuário."""
    user_id = callback.data.split(":")[-1]
    tenant, admin = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, admin.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        user = (await session.execute(
            select(User).where(User.id == UUID(user_id), User.tenant_id == tenant.id)
        )).scalar_one_or_none()
        if user:
            user.is_blocked = True
            user.block_reason = "Bloqueado pelo administrador"
            await session.commit()
            await callback.answer("Usuário bloqueado.")
        else:
            await callback.answer("Usuário não encontrado.")

    await state.clear()


@router.callback_query(F.data.startswith("admin:unblock_user:"))
async def unblock_user(callback: CallbackQuery, state: FSMContext):
    """Desbloqueia usuário."""
    user_id = callback.data.split(":")[-1]
    tenant, admin = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, admin.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        user = (await session.execute(
            select(User).where(User.id == UUID(user_id), User.tenant_id == tenant.id)
        )).scalar_one_or_none()
        if user:
            user.is_blocked = False
            user.block_reason = None
            await session.commit()
            await callback.answer("Usuário desbloqueado.")
        else:
            await callback.answer("Usuário não encontrado.")

    await state.clear()
