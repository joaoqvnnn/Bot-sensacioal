"""
Handlers administrativos de Usuários.

Seção 6 do painel: gerencia usuários do tenant.
Inclui pesquisa detalhada, visualização de todas as informações relevantes,
histórico completo (compras, recargas, saques, ajustes), bloqueio/desbloqueio
e ajuste manual de saldo com ledger e auditoria.
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
from bot.models.order import Order
from bot.models.withdrawal import Withdrawal
from bot.models.gift_card import GiftCardRedemption
from bot.models.referral import Referral
from bot.models.affiliate import AffiliatePoints
from bot.models.alert import AlertSubscription
from bot.models.user_block import UserBlock
from bot.services.user_service import get_tenant_for_bot, get_or_create_user
from bot.services.wallet_service import credit_wallet, debit_wallet
from bot.services.audit_service import audit_log

logger = logging.getLogger(__name__)

router = Router()


class AdminUsersStates(StatesGroup):
    WAITING_SEARCH_TERM = State()
    WAITING_ADJUST_AMOUNT = State()
    WAITING_ADJUST_REASON = State()
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


async def _find_user(session, tenant_id: UUID, term: str) -> Optional[User]:
    """Busca usuário por diferentes critérios."""
    user = None
    if term.isdigit():
        user = (await session.execute(
            select(User).where(
                User.tenant_id == tenant_id,
                User.telegram_id == int(term),
                User.deleted_at.is_(None),
            )
        )).scalar_one_or_none()
    elif term.startswith("@"):
        user = (await session.execute(
            select(User).where(
                User.tenant_id == tenant_id,
                User.username == term[1:],
                User.deleted_at.is_(None),
            )
        )).scalar_one_or_none()
    else:
        user = (await session.execute(
            select(User).where(
                User.tenant_id == tenant_id,
                ((User.whatsapp == term) | (User.email == term)),
                User.deleted_at.is_(None),
            )
        )).scalar_one_or_none()
    return user


@router.callback_query(F.data == "admin:manage_users")
async def manage_users(callback: CallbackQuery, state: FSMContext):
    """Menu inicial de gerenciamento de usuários."""
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
        "👥 USUÁRIOS\n\n"
        f"Total de usuários: {total_users}\n\n"
        "Escolha uma ação:"
    )
    buttons = [
        [create_button("🔎 Pesquisar usuário", "users_admin:search")],
        [create_button("📋 Listar recentes", "users_admin:recent")],
        [create_button("🔙 VOLTAR", "admin:main")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "users_admin:search")
async def search_user_start(callback: CallbackQuery, state: FSMContext):
    """Inicia pesquisa de usuário."""
    await state.set_state(AdminUsersStates.WAITING_SEARCH_TERM)
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


@router.message(AdminUsersStates.WAITING_SEARCH_TERM)
async def process_search_user(message: Message, state: FSMContext):
    """Processa pesquisa e exibe informações detalhadas do usuário."""
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

        target = await _find_user(session, tenant.id, term)
        if target is None:
            await message.answer("Usuário não encontrado.")
            await state.clear()
            return

        # Coleta estatísticas e informações
        wallet = (await session.execute(
            select(Wallet).where(Wallet.user_id == target.id, Wallet.tenant_id == tenant.id)
        )).scalar_one_or_none()
        balance_cents = int(wallet.balance_cents) if wallet else 0

        total_purchases = (await session.execute(
            select(func.count(Order.id)).where(
                Order.tenant_id == tenant.id,
                Order.user_id == target.id,
                Order.status == "COMPLETED",
                Order.deleted_at.is_(None),
            )
        )).scalar_one()

        total_spent = (await session.execute(
            select(func.sum(Order.total_cents)).where(
                Order.tenant_id == tenant.id,
                Order.user_id == target.id,
                Order.status == "COMPLETED",
                Order.deleted_at.is_(None),
            )
        )).scalar_one() or 0

        total_deposits = (await session.execute(
            select(func.sum(WalletLedger.amount_cents)).where(
                WalletLedger.tenant_id == tenant.id,
                WalletLedger.user_id == target.id,
                WalletLedger.entry_type == "deposit",
                WalletLedger.amount_cents > 0,
            )
        )).scalar_one() or 0

        total_withdrawals = (await session.execute(
            select(func.sum(Withdrawal.amount_cents)).where(
                Withdrawal.tenant_id == tenant.id,
                Withdrawal.user_id == target.id,
                Withdrawal.status == "PAID",
                Withdrawal.deleted_at.is_(None),
            )
        )).scalar_one() or 0

        gifts_redeemed = (await session.execute(
            select(func.count(GiftCardRedemption.id)).where(
                GiftCardRedemption.tenant_id == tenant.id,
                GiftCardRedemption.user_id == target.id,
                GiftCardRedemption.deleted_at.is_(None),
            )
        )).scalar_one()

        referrals_count = (await session.execute(
            select(func.count(Referral.id)).where(
                Referral.tenant_id == tenant.id,
                Referral.referrer_user_id == target.id,
                Referral.deleted_at.is_(None),
            )
        )).scalar_one()

        points_obj = (await session.execute(
            select(AffiliatePoints).where(
                AffiliatePoints.tenant_id == tenant.id,
                AffiliatePoints.user_id == target.id,
                AffiliatePoints.deleted_at.is_(None),
            )
        )).scalar_one_or_none()
        points = points_obj.points if points_obj else 0

        alerts_count = (await session.execute(
            select(func.count(AlertSubscription.id)).where(
                AlertSubscription.tenant_id == tenant.id,
                AlertSubscription.user_id == target.id,
                AlertSubscription.is_active == True,
                AlertSubscription.deleted_at.is_(None),
            )
        )).scalar_one()

        active_blocks = (await session.execute(
            select(func.count(UserBlock.id)).where(
                UserBlock.tenant_id == tenant.id,
                UserBlock.user_id == target.id,
                UserBlock.is_active == True,
                UserBlock.deleted_at.is_(None),
            )
        )).scalar_one()

    text = (
        "👤 Usuário encontrado:\n\n"
        f"🆔 Telegram ID: {target.telegram_id}\n"
        f"👤 Nome: {target.first_name or ''} {target.last_name or ''}\n"
        f"📱 Username: @{target.username or 'N/A'}\n"
        f"📲 WhatsApp: {target.whatsapp or 'N/A'}\n"
        f"📧 E-mail: {target.email or 'N/A'}\n"
        f"🚫 Bloqueado: {'Sim' if target.is_blocked else 'Não'}\n"
        f"📅 Cadastro: {target.registered_at.strftime('%d/%m/%Y %H:%M') if target.registered_at else 'N/A'}\n"
        f"🕒 Última atividade: {target.last_login_at.strftime('%d/%m/%Y %H:%M') if target.last_login_at else 'N/A'}\n\n"
        "💰 Financeiro:\n"
        f"Saldo: {cents_to_brl(balance_cents)}\n"
        f"Depósitos: {cents_to_brl(int(total_deposits))}\n"
        f"Saques: {cents_to_brl(int(total_withdrawals))}\n\n"
        "🛒 Atividade:\n"
        f"Compras: {total_purchases}\n"
        f"Total gasto: {cents_to_brl(int(total_spent))}\n"
        f"Gift Cards: {gifts_redeemed}\n"
        f"Indicações: {referrals_count}\n"
        f"Pontos: {points}\n"
        f"Alertas ativos: {alerts_count}\n"
        f"Bloqueios ativos: {active_blocks}\n"
    )
    buttons = [
        [create_button("📋 Histórico de compras", f"users_admin:history_purchases:{target.id}")],
        [create_button("📋 Histórico de recargas", f"users_admin:history_deposits:{target.id}")],
        [create_button("📋 Histórico de saques", f"users_admin:history_withdrawals:{target.id}")],
        [create_button("📋 Histórico de ajustes", f"users_admin:history_adjustments:{target.id}")],
        [create_button("💰 Ajustar saldo", f"users_admin:adjust:{target.id}")],
        [create_button("🚫 Bloquear usuário", f"users_admin:block:{target.id}") if not target.is_blocked else create_button("✅ Desbloquear", f"users_admin:unblock:{target.id}")],
        [create_button("🔙 VOLTAR", "admin:manage_users")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(text, reply_markup=keyboard)
    await state.clear()


# ----------------------------------------------------------------------
# HISTÓRICOS
# ----------------------------------------------------------------------

async def _show_history(callback: CallbackQuery, user_id: UUID, history_type: str, title: str):
    """Exibe histórico específico do usuário."""
    tenant, admin = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, admin.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        if history_type == "purchases":
            records = (await session.execute(
                select(Order).where(
                    Order.tenant_id == tenant.id,
                    Order.user_id == user_id,
                    Order.deleted_at.is_(None),
                ).order_by(Order.created_at.desc()).limit(10)
            )).scalars().all()
            lines = [f"📋 {title}:\n"]
            for r in records:
                lines.append(f"• {r.created_at.strftime('%d/%m/%Y %H:%M')} - {cents_to_brl(int(r.total_cents))} - {r.status}")
        elif history_type == "deposits":
            records = (await session.execute(
                select(WalletLedger).where(
                    WalletLedger.tenant_id == tenant.id,
                    WalletLedger.user_id == user_id,
                    WalletLedger.entry_type == "deposit",
                    WalletLedger.amount_cents > 0,
                    WalletLedger.deleted_at.is_(None),
                ).order_by(WalletLedger.created_at.desc()).limit(10)
            )).scalars().all()
            lines = [f"📋 {title}:\n"]
            for r in records:
                lines.append(f"• {r.created_at.strftime('%d/%m/%Y %H:%M')} - {cents_to_brl(int(r.amount_cents))}")
        elif history_type == "withdrawals":
            records = (await session.execute(
                select(Withdrawal).where(
                    Withdrawal.tenant_id == tenant.id,
                    Withdrawal.user_id == user_id,
                    Withdrawal.deleted_at.is_(None),
                ).order_by(Withdrawal.created_at.desc()).limit(10)
            )).scalars().all()
            lines = [f"📋 {title}:\n"]
            for r in records:
                lines.append(f"• {r.created_at.strftime('%d/%m/%Y %H:%M')} - {cents_to_brl(int(r.amount_cents))} - {r.status}")
        elif history_type == "adjustments":
            records = (await session.execute(
                select(WalletLedger).where(
                    WalletLedger.tenant_id == tenant.id,
                    WalletLedger.user_id == user_id,
                    WalletLedger.entry_type == "adjustment",
                    WalletLedger.deleted_at.is_(None),
                ).order_by(WalletLedger.created_at.desc()).limit(10)
            )).scalars().all()
            lines = [f"📋 {title}:\n"]
            for r in records:
                sign = "+" if int(r.amount_cents) > 0 else ""
                lines.append(f"• {r.created_at.strftime('%d/%m/%Y %H:%M')} - {sign}{cents_to_brl(int(r.amount_cents))} - {r.description}")
        else:
            lines = ["Histórico indisponível."]

    text = "\n".join(lines) if lines else "Nenhum registro."
    buttons = [[create_button("🔙 VOLTAR", "admin:manage_users")]]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data.startswith("users_admin:history_purchases:"))
async def history_purchases(callback: CallbackQuery, state: FSMContext):
    user_id = UUID(callback.data.split(":")[-1])
    await _show_history(callback, user_id, "purchases", "Histórico de compras")


@router.callback_query(F.data.startswith("users_admin:history_deposits:"))
async def history_deposits(callback: CallbackQuery, state: FSMContext):
    user_id = UUID(callback.data.split(":")[-1])
    await _show_history(callback, user_id, "deposits", "Histórico de recargas")


@router.callback_query(F.data.startswith("users_admin:history_withdrawals:"))
async def history_withdrawals(callback: CallbackQuery, state: FSMContext):
    user_id = UUID(callback.data.split(":")[-1])
    await _show_history(callback, user_id, "withdrawals", "Histórico de saques")


@router.callback_query(F.data.startswith("users_admin:history_adjustments:"))
async def history_adjustments(callback: CallbackQuery, state: FSMContext):
    user_id = UUID(callback.data.split(":")[-1])
    await _show_history(callback, user_id, "adjustments", "Histórico de ajustes")


# ----------------------------------------------------------------------
# AJUSTE DE SALDO
# ----------------------------------------------------------------------

@router.callback_query(F.data.startswith("users_admin:adjust:"))
async def adjust_balance_start(callback: CallbackQuery, state: FSMContext):
    """Inicia ajuste de saldo."""
    user_id = UUID(callback.data.split(":")[-1])
    await state.update_data(adjust_user_id=str(user_id))
    await state.set_state(AdminUsersStates.WAITING_ADJUST_AMOUNT)
    text = "Digite o valor do ajuste (ex: 10.00 para crédito, -5.00 para débito):"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "admin:manage_users")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminUsersStates.WAITING_ADJUST_AMOUNT)
async def process_adjust_amount(message: Message, state: FSMContext):
    """Recebe valor e pede motivo obrigatório."""
    try:
        amount_cents = int(float(message.text.strip().replace(",", ".")) * 100)
        if amount_cents == 0:
            raise ValueError
    except ValueError:
        await message.answer("Valor inválido.")
        return

    await state.update_data(adjust_amount_cents=amount_cents)
    await state.set_state(AdminUsersStates.WAITING_ADJUST_REASON)
    await message.answer("Digite o motivo do ajuste (obrigatório):")


@router.message(AdminUsersStates.WAITING_ADJUST_REASON)
async def process_adjust_reason(message: Message, state: FSMContext):
    """Recebe motivo e efetua ajuste com ledger e auditoria."""
    reason = message.text.strip()
    if not reason:
        await message.answer("Motivo obrigatório.")
        return

    data = await state.get_data()
    user_id = UUID(data["adjust_user_id"])
    amount_cents = data["adjust_amount_cents"]

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
            if amount_cents > 0:
                await credit_wallet(
                    session,
                    tenant_id=tenant.id,
                    user_id=user_id,
                    amount_cents=amount_cents,
                    entry_type="adjustment",
                    description=f"Ajuste manual: {reason}",
                )
            else:
                await debit_wallet(
                    session,
                    tenant_id=tenant.id,
                    user_id=user_id,
                    amount_cents=abs(amount_cents),
                    entry_type="adjustment",
                    description=f"Ajuste manual: {reason}",
                )
        except ValueError as e:
            await message.answer(f"❌ {e}")
            await state.clear()
            return

        await audit_log(
            session,
            tenant_id=tenant.id,
            action="wallet.manual_adjustment",
            description=f"Ajuste de {cents_to_brl(amount_cents)} - {reason}",
            actor_user_id=admin.id,
            target_user_id=user_id,
        )

    await state.clear()
    await message.answer(f"✅ Saldo ajustado em {cents_to_brl(amount_cents)}.")


# ----------------------------------------------------------------------
# BLOQUEIO / DESBLOQUEIO
# ----------------------------------------------------------------------

@router.callback_query(F.data.startswith("users_admin:block:"))
async def block_user_start(callback: CallbackQuery, state: FSMContext):
    """Inicia bloqueio de usuário."""
    user_id = UUID(callback.data.split(":")[-1])
    await state.update_data(block_user_id=str(user_id))
    await state.set_state(AdminUsersStates.WAITING_BLOCK_REASON)
    text = "Digite o motivo do bloqueio:"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "admin:manage_users")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminUsersStates.WAITING_BLOCK_REASON)
async def process_block_reason(message: Message, state: FSMContext):
    """Bloqueia usuário com motivo e auditoria."""
    reason = message.text.strip()
    if not reason:
        await message.answer("Motivo obrigatório.")
        return

    data = await state.get_data()
    user_id = UUID(data["block_user_id"])

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

        user = (await session.execute(
            select(User).where(User.id == user_id, User.tenant_id == tenant.id)
        )).scalar_one_or_none()
        if user:
            user.is_blocked = True
            user.block_reason = reason
            await session.commit()
            await audit_log(
                session,
                tenant_id=tenant.id,
                action="user.block",
                description=f"Bloqueio: {reason}",
                actor_user_id=admin.id,
                target_user_id=user_id,
            )
            await message.answer("✅ Usuário bloqueado.")
        else:
            await message.answer("Usuário não encontrado.")

    await state.clear()


@router.callback_query(F.data.startswith("users_admin:unblock:"))
async def unblock_user(callback: CallbackQuery, state: FSMContext):
    """Desbloqueia usuário."""
    user_id = UUID(callback.data.split(":")[-1])
    tenant, admin = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, admin.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        user = (await session.execute(
            select(User).where(User.id == user_id, User.tenant_id == tenant.id)
        )).scalar_one_or_none()
        if user:
            user.is_blocked = False
            user.block_reason = None
            await session.commit()
            await audit_log(
                session,
                tenant_id=tenant.id,
                action="user.unblock",
                description="Desbloqueio",
                actor_user_id=admin.id,
                target_user_id=user_id,
            )
            await callback.answer("Usuário desbloqueado.")
        else:
            await callback.answer("Usuário não encontrado.")

    await manage_users(callback, state)


# ----------------------------------------------------------------------
# LISTAR RECENTES
# ----------------------------------------------------------------------

@router.callback_query(F.data == "users_admin:recent")
async def list_recent_users(callback: CallbackQuery, state: FSMContext):
    """Lista os 10 usuários mais recentes."""
    tenant, admin = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, admin.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        users = (await session.execute(
            select(User).where(
                User.tenant_id == tenant.id,
                User.deleted_at.is_(None),
            ).order_by(User.created_at.desc()).limit(10)
        )).scalars().all()

    if not users:
        text = "Nenhum usuário cadastrado."
    else:
        text = "👥 Usuários recentes:\n\n"
        for u in users:
            text += f"• {u.first_name or u.username} (ID: {u.telegram_id}) - {u.created_at.strftime('%d/%m/%Y')}\n"

    buttons = [[create_button("🔙 VOLTAR", "admin:manage_users")]]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)
