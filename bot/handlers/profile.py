"""
Handlers de perfil do usuário.

Exibe dados reais (ID, saldo, WhatsApp, movimentações), histórico de compras,
alteração de WhatsApp e resgate de Gift Card. Tudo com edição da mesma mensagem
e botões de voltar.
"""

import logging
from typing import Optional
from uuid import UUID

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import func, select

from bot.core.database import get_async_session_factory
from bot.core.utils import cents_to_brl, paginate
from bot.keyboards.utils import create_button, add_back_button, create_pagination_buttons
from bot.services.user_service import get_tenant_for_bot, get_or_create_user
from bot.services.wallet_service import get_balance
from bot.services.gift_card_service import redeem_gift_card
from bot.models.order import Order, OrderItem
from bot.models.user import User
from bot.models.tenant import Tenant

logger = logging.getLogger(__name__)

router = Router()


class ProfileStates(StatesGroup):
    WAITING_WHATSAPP = State()
    WAITING_GIFT_CODE = State()


async def _get_tenant_and_user(callback: CallbackQuery):
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


async def _edit_or_answer(callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup):
    """Edita a mensagem atual, se possível."""
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard)
    await callback.answer()


async def _get_user_stats(session, tenant_id: UUID, user_id: UUID) -> dict:
    """Retorna estatísticas reais do usuário."""
    # Compras realizadas (pedidos completos)
    purchases_stmt = select(func.count(Order.id)).where(
        Order.tenant_id == tenant_id,
        Order.user_id == user_id,
        Order.status == "COMPLETED",
        Order.deleted_at.is_(None),
    )
    purchases_count = (await session.execute(purchases_stmt)).scalar_one()

    # Total gasto
    spent_stmt = select(func.sum(Order.total_cents)).where(
        Order.tenant_id == tenant_id,
        Order.user_id == user_id,
        Order.status == "COMPLETED",
        Order.deleted_at.is_(None),
    )
    total_spent = (await session.execute(spent_stmt)).scalar_one() or 0

    # Pix inseridos (créditos de deposit)
    deposits_stmt = select(func.sum(WalletLedger.amount_cents)).where(
        WalletLedger.tenant_id == tenant_id,
        WalletLedger.user_id == user_id,
        WalletLedger.entry_type == "deposit",
        WalletLedger.amount_cents > 0,
    )
    total_deposits = (await session.execute(deposits_stmt)).scalar_one() or 0

    # Gifts resgatados (entry_type gift)
    gifts_stmt = select(func.sum(WalletLedger.amount_cents)).where(
        WalletLedger.tenant_id == tenant_id,
        WalletLedger.user_id == user_id,
        WalletLedger.entry_type == "gift",
        WalletLedger.amount_cents > 0,
    )
    total_gifts = (await session.execute(gifts_stmt)).scalar_one() or 0

    return {
        "purchases": int(purchases_count),
        "spent": int(total_spent),
        "deposits": int(total_deposits),
        "gifts": int(total_gifts),
    }


@router.callback_query(F.data == "menu:profile")
async def show_profile(callback: CallbackQuery, state: FSMContext):
    """Exibe o perfil do usuário com dados reais."""
    tenant, user = await _get_tenant_and_user(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        balance_cents = await get_balance(session, tenant.id, user.id)
        stats = await _get_user_stats(session, tenant.id, user.id)

    whatsapp = user.whatsapp or "Não cadastrado"

    text = (
        "👤 Meu perfil\n"
        "🔍 Veja aqui os detalhes da sua conta:\n\n"
        "- 👤 Informações:\n"
        f"🆔 ID da Carteira: {user.telegram_id}\n"
        f"💰 Saldo Atual: {cents_to_brl(balance_cents)}\n"
        f"📲 Seu Whatsapp: {whatsapp}\n\n"
        "─── 📊 Suas Movimentações:\n"
        f"🛒 Compras Realizadas: {stats['purchases']}\n"
        f"💰 Total Gasto Em Compras: {cents_to_brl(stats['spent'])}\n"
        f"💠 Pix Inseridos: {cents_to_brl(stats['deposits'])}\n"
        f"🎁 Gifts Resgatados: {cents_to_brl(stats['gifts'])}"
    )

    buttons = [
        [create_button("🛍 HISTÓRICO DE COMPRA", "profile:history")],
        [create_button("🎁 RESGATAR GIFT CARD", "profile:gift")],
        [create_button("✏️ ALTERAR DADOS", "profile:change_data")],
        [create_button("🔙 VOLTAR", "menu:back")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "profile:history")
async def show_history(callback: CallbackQuery, state: FSMContext, page: int = 1):
    """Exibe histórico de compras com paginação."""
    tenant, user = await _get_tenant_and_user(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        stmt = (
            select(Order)
            .where(
                Order.tenant_id == tenant.id,
                Order.user_id == user.id,
                Order.deleted_at.is_(None),
            )
            .order_by(Order.created_at.desc())
        )
        result = await session.execute(stmt)
        orders = list(result.scalars().all())

    if not orders:
        text = "📋 Você ainda não possui compras."
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[create_button("🔙 VOLTAR", "menu:profile")]]
        )
        await _edit_or_answer(callback, text, keyboard)
        return

    # Paginação simples (10 por página)
    per_page = 3
    total_pages = max(1, (len(orders) + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    end = start + per_page
    page_orders = orders[start:end]

    text = f"🛍 Compras ({len(orders)}):\n\n"
    for order in page_orders:
        created = order.created_at.strftime("%d/%m/%Y")
        text += (
            f"⏰ Data: {created}\n"
            f"💰 Valor: {cents_to_brl(order.total_cents)}\n"
            f"🎫 ID: {order.id}\n"
            f"Status: {order.status}\n"
            "─────────────\n"
        )

    # Botões de paginação + voltar
    nav_buttons = create_pagination_buttons(page, total_pages, "profile:history")
    nav_buttons.append(create_button("🔙 VOLTAR", "menu:profile"))
    keyboard = InlineKeyboardMarkup(inline_keyboard=[nav_buttons])
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data.startswith("profile:history:"))
async def history_page_callback(callback: CallbackQuery, state: FSMContext):
    """Trata paginação do histórico."""
    # Extrai página do callback: profile:history:2
    parts = callback.data.split(":")
    if len(parts) == 3 and parts[1] == "history" and parts[2].isdigit():
        page = int(parts[2])
        await show_history(callback, state, page)
    else:
        await show_history(callback, state)


@router.callback_query(F.data == "profile:change_data")
async def show_change_data(callback: CallbackQuery, state: FSMContext):
    """Exibe opções de alteração de dados."""
    tenant, user = await _get_tenant_and_user(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    whatsapp = user.whatsapp or "Não cadastrado"

    text = (
        "✏️ Alterar Dados\n"
        "Selecione o dado que deseja alterar:\n\n"
        f"📱 WhatsApp: {whatsapp}"
    )
    buttons = [
        [create_button("📱 WhatsApp", "profile:change_whatsapp")],
        [create_button("🔙 VOLTAR", "menu:profile")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "profile:change_whatsapp")
async def change_whatsapp(callback: CallbackQuery, state: FSMContext):
    """Solicita novo número de WhatsApp."""
    await state.set_state(ProfileStates.WAITING_WHATSAPP)
    await callback.message.edit_text(
        "📱 Envie seu número de WhatsApp\n"
        "Formato: DDD + Número (apenas números)\n"
        "Exemplo: 11999998888\n"
        "⚠️ Envie 'remover' para remover o número cadastrado.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[create_button("🔙 CANCELAR", "menu:profile")]]
        ),
    )
    await callback.answer()


@router.message(ProfileStates.WAITING_WHATSAPP)
async def process_whatsapp(message: Message, state: FSMContext):
    """Processa entrada do usuário para WhatsApp."""
    text = message.text.strip() if message.text else ""
    tenant = None
    async with get_async_session_factory() as session:
        tenant = await get_tenant_for_bot(session, message.bot.username)
        if tenant is None:
            await message.answer("Sistema indisponível.")
            await state.clear()
            return

        user = await get_or_create_user(
            session=session,
            tenant=tenant,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
        )

        if text.lower() == "remover":
            user.whatsapp = None
            await session.commit()
            await message.answer("✅ WhatsApp removido com sucesso!")
        else:
            # Valida formato (somente dígitos, 10 a 13)
            digits = "".join(ch for ch in text if ch.isdigit())
            if 10 <= len(digits) <= 13:
                user.whatsapp = digits
                await session.commit()
                await message.answer(f"✅ WhatsApp atualizado: {digits}")
            else:
                await message.answer(
                    "❌ Formato inválido! Envie apenas números com DDD.\nExemplo: 11999998888"
                )
                return  # mantém estado para tentar novamente

    await state.clear()
    # Voltar para perfil (enviar novo comando? melhor não, apenas mensagem)


@router.callback_query(F.data == "profile:gift")
async def ask_gift_code(callback: CallbackQuery, state: FSMContext):
    """Solicita código do gift card."""
    await state.set_state(ProfileStates.WAITING_GIFT_CODE)
    await callback.message.edit_text(
        "🎁 RESGATAR GIFT CARD\n"
        "Digite o código do seu gift card abaixo:\n"
        "Exemplo: ABC123XYZ456",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[create_button("🔙 CANCELAR", "menu:profile")]]
        ),
    )
    await callback.answer()


@router.message(ProfileStates.WAITING_GIFT_CODE)
async def process_gift_code(message: Message, state: FSMContext):
    """Processa resgate do gift card."""
    code = message.text.strip() if message.text else ""
    tenant = None
    async with get_async_session_factory() as session:
        tenant = await get_tenant_for_bot(session, message.bot.username)
        if tenant is None:
            await message.answer("Sistema indisponível.")
            await state.clear()
            return

        user = await get_or_create_user(
            session=session,
            tenant=tenant,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
        )

        # Gera idempotency key simples (pode usar message.message_id)
        idempotency_key = f"gift:{message.from_user.id}:{message.message_id}"

        result = await redeem_gift_card(
            session=session,
            tenant_id=tenant.id,
            user=user,
            code=code,
            idempotency_key=idempotency_key,
        )

        if result["status"] == "SUCCESS":
            await message.answer(
                f"🎉 Gift Card resgatado!\n"
                f"💰 Valor creditado: {cents_to_brl(result['amount_cents'])}"
            )
        elif result["status"] == "INVALID":
            await message.answer("❌ Gift não encontrado.")
        elif result["status"] == "ALREADY_REDEEMED":
            await message.answer("❌ Gift já resgatado.")
        elif result["status"] == "EXPIRED":
            await message.answer("❌ Gift expirado.")
        else:
            await message.answer("❌ Não foi possível resgatar o gift card.")

    await state.clear()
