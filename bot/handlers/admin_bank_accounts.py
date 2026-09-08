"""
Handlers administrativos de Contas Bancárias.

Seção 18 do painel: gerencia contas bancárias cadastradas pelos usuários.
Permite buscar usuário, listar suas contas (mascaradas) e remover.
Dados sensíveis permanecem criptografados.
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
from bot.models.withdrawal import WithdrawalAccount
from bot.models.user import User
from bot.services.user_service import get_tenant_for_bot, get_or_create_user

logger = logging.getLogger(__name__)

router = Router()


class AdminBankAccountsStates(StatesGroup):
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


async def _edit_or_answer(callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup):
    """Edita a mensagem atual, se possível."""
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "bank_admin:main")
async def bank_accounts_main(callback: CallbackQuery, state: FSMContext):
    """Menu principal de contas bancárias: pede usuário para busca."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

    await state.set_state(AdminBankAccountsStates.WAITING_USER_SEARCH)
    text = "Digite o Telegram ID, @username, WhatsApp ou e-mail do usuário para listar suas contas bancárias:"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "admin:main")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminBankAccountsStates.WAITING_USER_SEARCH)
async def process_bank_user_search(message: Message, state: FSMContext):
    """Busca usuário e lista contas bancárias mascaradas."""
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

        accounts = (await session.execute(
            select(WithdrawalAccount).where(
                WithdrawalAccount.tenant_id == tenant.id,
                WithdrawalAccount.user_id == target.id,
                WithdrawalAccount.deleted_at.is_(None),
            )
        )).scalars().all()

    if not accounts:
        text = f"Nenhuma conta bancária para {target.first_name or target.username}."
        buttons = [[create_button("🔙 VOLTAR", "bank_admin:main")]]
    else:
        text = f"🏦 Contas bancárias de {target.first_name or target.username}:\n\n"
        buttons = []
        for account in accounts:
            # Exibe apenas tipo e titular mascarado; não descriptografa dados completos
            account_type = "PIX" if account.account_type.upper() == "PIX" else "BANCO"
            holder = account.holder_name or "Não informado"
            # Mascarar titular (apenas primeiro nome e última letra)
            if holder and holder != "Não informado":
                parts = holder.split()
                if len(parts) > 1:
                    masked_holder = parts[0][0] + "*" * (len(parts[0]) - 1) + " " + parts[-1][0] + "*"
                else:
                    masked_holder = holder[0] + "*" * (len(holder) - 1) if len(holder) > 1 else holder
            else:
                masked_holder = holder

            text += f"• Tipo: {account_type}\n  Titular: {masked_holder}\n"
            buttons.append([create_button(f"Remover conta {account.id}", f"bank_admin:remove:{account.id}")])

        buttons.append([create_button("🔙 VOLTAR", "bank_admin:main")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(text, reply_markup=keyboard)
    await state.clear()


@router.callback_query(F.data.startswith("bank_admin:remove:"))
async def remove_bank_account(callback: CallbackQuery, state: FSMContext):
    """Remove (soft delete) uma conta bancária."""
    account_id = UUID(callback.data.split(":")[-1])
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        account = (await session.execute(
            select(WithdrawalAccount).where(
                WithdrawalAccount.id == account_id,
                WithdrawalAccount.tenant_id == tenant.id,
            )
        )).scalar_one_or_none()
        if account:
            account.soft_delete()
            await session.commit()
            await callback.answer("Conta removida.")
        else:
            await callback.answer("Conta não encontrada.")

    # Volta para a tela de busca
    await bank_accounts_main(callback, state)
