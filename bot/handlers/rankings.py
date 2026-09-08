"""
Handlers de rankings (Top Compradores).

Exibe rankings reais:
- Serviços mais vendidos
- Usuários que mais recarregaram
- Usuários que mais compraram
- Usuários com maior saldo

Tudo com edição da mesma mensagem, abas e botão de voltar.
"""

import logging
from typing import List, Tuple, Optional
from uuid import UUID

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from sqlalchemy import select, func, desc

from bot.core.config import settings
from bot.core.database import get_async_session_factory
from bot.core.utils import cents_to_brl
from bot.keyboards.utils import create_button
from bot.models.order import Order, OrderItem
from bot.models.product import Product
from bot.models.user import User
from bot.models.wallet import Wallet, WalletLedger
from bot.services.user_service import get_tenant_for_bot, get_or_create_user

logger = logging.getLogger(__name__)

router = Router()


async def _get_tenant_and_user(callback: CallbackQuery):
    """Obtém tenant e usuário a partir do callback."""
    factory = get_async_session_factory()
    async with factory() as session:
        tenant = await get_tenant_for_bot(session, settings.TELEGRAM_BOT_USERNAME)
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


async def _get_ranking_services(session, tenant_id: UUID, limit: int = 10) -> List[Tuple[str, int]]:
    """Retorna lista de (nome_produto, total_vendas) para ranking de serviços."""
    stmt = (
        select(Product.name, func.count(OrderItem.id).label("total"))
        .join(OrderItem, OrderItem.product_id == Product.id)
        .where(
            OrderItem.tenant_id == tenant_id,
            OrderItem.deleted_at.is_(None),
        )
        .group_by(Product.name)
        .order_by(desc("total"))
        .limit(limit)
    )
    result = await session.execute(stmt)
    return [(row[0], int(row[1])) for row in result.all()]


async def _get_ranking_recharges(session, tenant_id: UUID, limit: int = 10) -> List[Tuple[str, int]]:
    """Retorna lista de (nome_usuario, total_depositado) para ranking de recargas."""
    stmt = (
        select(
            User.first_name,
            User.username,
            func.coalesce(func.sum(WalletLedger.amount_cents), 0).label("total"),
        )
        .join(WalletLedger, WalletLedger.user_id == User.id)
        .where(
            WalletLedger.tenant_id == tenant_id,
            WalletLedger.entry_type == "deposit",
            WalletLedger.amount_cents > 0,
            WalletLedger.deleted_at.is_(None),
        )
        .group_by(User.id)
        .order_by(desc("total"))
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows = result.all()
    ranking = []
    for first_name, username, total in rows:
        display = username or first_name or f"ID: {first_name}"
        ranking.append((display, int(total)))
    return ranking


async def _get_ranking_purchases(session, tenant_id: UUID, limit: int = 10) -> List[Tuple[str, int]]:
    """Retorna lista de (nome_usuario, total_gasto) para ranking de compras."""
    stmt = (
        select(
            User.first_name,
            User.username,
            func.coalesce(func.sum(Order.total_cents), 0).label("total"),
        )
        .join(Order, Order.user_id == User.id)
        .where(
            Order.tenant_id == tenant_id,
            Order.status == "COMPLETED",
            Order.deleted_at.is_(None),
        )
        .group_by(User.id)
        .order_by(desc("total"))
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows = result.all()
    ranking = []
    for first_name, username, total in rows:
        display = username or first_name or f"ID: {first_name}"
        ranking.append((display, int(total)))
    return ranking


async def _get_ranking_balance(session, tenant_id: UUID, limit: int = 10) -> List[Tuple[str, int]]:
    """Retorna lista de (nome_usuario, saldo) para ranking de saldo."""
    stmt = (
        select(
            User.first_name,
            User.username,
            func.coalesce(Wallet.balance_cents, 0).label("balance"),
        )
        .join(Wallet, Wallet.user_id == User.id)
        .where(
            Wallet.tenant_id == tenant_id,
            Wallet.deleted_at.is_(None),
        )
        .order_by(desc("balance"))
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows = result.all()
    ranking = []
    for first_name, username, balance in rows:
        display = username or first_name or f"ID: {first_name}"
        ranking.append((display, int(balance)))
    return ranking


def _format_ranking(title: str, ranking: List[Tuple[str, int]], value_label: str) -> str:
    """Formata uma lista de ranking em texto."""
    if not ranking:
        return f"{title}\n\nNenhum dado disponível."

    lines = [title, ""]
    medals = ["🥇", "🥈", "🥉"]
    for i, (name, value) in enumerate(ranking, start=1):
        medal = medals[i-1] if i <= 3 else f"{i}°"
        lines.append(f"{medal} {name} - {value_label}: {value}")
    return "\n".join(lines)


def _get_rankings_keyboard(active_tab: str) -> InlineKeyboardMarkup:
    """Retorna teclado de abas de rankings."""
    tabs = [
        ("☑️ SERVIÇOS", "rankings:services"),
        ("☑️ RECARGAS", "rankings:recharges"),
        ("☑️ COMPRAS", "rankings:purchases"),
        ("☑️ SALDO", "rankings:balance"),
    ]
    buttons = []
    for label, callback in tabs:
        if callback.endswith(active_tab):
            label = label.replace("☑️", "✅")
        buttons.append(create_button(label, callback))
    keyboard_rows = [buttons[:2], buttons[2:]]
    keyboard_rows.append([create_button("🔙 VOLTAR", "menu:back")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard_rows)


@router.callback_query(F.data == "menu:rankings")
async def show_rankings(callback: CallbackQuery, state: FSMContext):
    """Exibe o ranking de serviços como padrão."""
    await show_services_ranking(callback, state)


@router.callback_query(F.data == "rankings:services")
async def show_services_ranking(callback: CallbackQuery, state: FSMContext):
    """Exibe ranking de serviços mais vendidos."""
    tenant, user = await _get_tenant_and_user(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    factory = get_async_session_factory()
    async with factory() as session:
        ranking = await _get_ranking_services(session, tenant.id)

    text = _format_ranking(
        "🏆 Ranking dos serviços mais vendidos (deste mês)",
        ranking,
        "pedidos",
    )
    keyboard = _get_rankings_keyboard("services")
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "rankings:recharges")
async def show_recharges_ranking(callback: CallbackQuery, state: FSMContext):
    """Exibe ranking de recargas."""
    tenant, user = await _get_tenant_and_user(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    factory = get_async_session_factory()
    async with factory() as session:
        ranking = await _get_ranking_recharges(session, tenant.id)

    text = _format_ranking(
        "🏆 Ranking dos usuários que mais recarregaram (deste mês)",
        ranking,
        "total",
    )
    keyboard = _get_rankings_keyboard("recharges")
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "rankings:purchases")
async def show_purchases_ranking(callback: CallbackQuery, state: FSMContext):
    """Exibe ranking de compras."""
    tenant, user = await _get_tenant_and_user(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    factory = get_async_session_factory()
    async with factory() as session:
        ranking = await _get_ranking_purchases(session, tenant.id)

    text = _format_ranking(
        "🏆 Ranking dos usuários que mais compraram (deste mês)",
        ranking,
        "total",
    )
    keyboard = _get_rankings_keyboard("purchases")
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "rankings:balance")
async def show_balance_ranking(callback: CallbackQuery, state: FSMContext):
    """Exibe ranking de saldo."""
    tenant, user = await _get_tenant_and_user(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    factory = get_async_session_factory()
    async with factory() as session:
        ranking = await _get_ranking_balance(session, tenant.id)

    text = _format_ranking(
        "🏆 Ranking dos usuários com mais saldo no bot",
        ranking,
        "saldo",
    )
    keyboard = _get_rankings_keyboard("balance")
    await _edit_or_answer(callback, text, keyboard)
