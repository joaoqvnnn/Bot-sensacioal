"""
Handlers de área de afiliados.

Exibe link de afiliado, quantidade de indicações, comissões acumuladas,
pontos e possibilita solicitar saque (futuro). Nada fictício.
"""

import logging
from typing import Optional
from uuid import UUID

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from sqlalchemy import func, select

from bot.core.config import settings
from bot.core.database import get_async_session_factory
from bot.core.utils import cents_to_brl
from bot.keyboards.utils import create_button
from bot.models.referral import Referral, AffiliateCommission, AffiliatePoints
from bot.models.user import User
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


async def _get_affiliate_stats(session, tenant_id: UUID, user_id: UUID) -> dict:
    """Retorna estatísticas reais do afiliado."""
    referrals_count_stmt = select(func.count(Referral.id)).where(
        Referral.tenant_id == tenant_id,
        Referral.referrer_user_id == user_id,
        Referral.deleted_at.is_(None),
    )
    referrals_count = (await session.execute(referrals_count_stmt)).scalar_one()

    total_commission_stmt = select(func.sum(AffiliateCommission.amount_cents)).where(
        AffiliateCommission.tenant_id == tenant_id,
        AffiliateCommission.user_id == user_id,
        AffiliateCommission.deleted_at.is_(None),
        AffiliateCommission.status.in_(["PENDING", "PAID"]),
    )
    total_commission = (await session.execute(total_commission_stmt)).scalar_one() or 0

    available_commission_stmt = select(func.sum(AffiliateCommission.amount_cents)).where(
        AffiliateCommission.tenant_id == tenant_id,
        AffiliateCommission.user_id == user_id,
        AffiliateCommission.deleted_at.is_(None),
        AffiliateCommission.status == "PAID",
    )
    available_commission = (await session.execute(available_commission_stmt)).scalar_one() or 0

    points_stmt = select(AffiliatePoints).where(
        AffiliatePoints.tenant_id == tenant_id,
        AffiliatePoints.user_id == user_id,
        AffiliatePoints.deleted_at.is_(None),
    )
    points_obj = (await session.execute(points_stmt)).scalar_one_or_none()
    points = points_obj.points if points_obj else 0

    return {
        "referrals": int(referrals_count),
        "total_commission": int(total_commission),
        "available_commission": int(available_commission),
        "points": points,
    }


@router.callback_query(F.data == "menu:affiliates")
async def show_affiliate_menu(callback: CallbackQuery, state: FSMContext):
    """Exibe resumo da área de afiliados."""
    tenant, user = await _get_tenant_and_user(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    factory = get_async_session_factory()
    async with factory() as session:
        stats = await _get_affiliate_stats(session, tenant.id, user.id)

    bot_username = settings.TELEGRAM_BOT_USERNAME
    referral_code = f"ref{user.id}"  # simplificação; futuramente usar campo próprio
    affiliate_link = f"https://t.me/{bot_username}?start={referral_code}"

    text = (
        "💰 PROGRAMA DE AFILIADOS\n"
        "⚙️ Status: Ativo\n\n"
        f"👥 Indicações: {stats['referrals']}\n"
        f"🪙 Total ganho: {cents_to_brl(stats['total_commission'])}\n"
        f"🔥 Saldo de comissões: {cents_to_brl(stats['available_commission'])}\n"
        f"🌟 Pontos: {stats['points']}\n\n"
        "🔗 Seu link:\n"
        f"{affiliate_link}"
    )

    buttons = [
        [create_button("📊 HISTÓRICO DE SAQUE", "affiliate:withdrawals")],
        [create_button("🔄 CONVERTER PONTOS", "affiliate:convert_points")],
        [create_button("🔙 VOLTAR", "menu:back")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "affiliate:withdrawals")
async def show_withdrawals(callback: CallbackQuery, state: FSMContext):
    """Exibe histórico de saques (placeholder real)."""
    tenant, user = await _get_tenant_and_user(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    text = (
        "📊 HISTÓRICO DE SAQUES\n"
        "Você ainda não solicitou nenhum saque.\n"
        "📉 Saque mínimo atual: R$ 20.00"
    )
    buttons = [
        [create_button("💠 SOLICITAR SAQUE", "affiliate:request_withdrawal")],
        [create_button("🔙 VOLTAR", "menu:affiliates")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "affiliate:request_withdrawal")
async def request_withdrawal(callback: CallbackQuery, state: FSMContext):
    """Solicita saque (placeholder, implementação futura)."""
    text = "💸 Em breve: solicitação de saque completa."
    buttons = [[create_button("🔙 VOLTAR", "affiliate:withdrawals")]]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "affiliate:convert_points")
async def convert_points(callback: CallbackQuery, state: FSMContext):
    """Converte pontos em saldo (placeholder)."""
    text = "🔄 Em breve: conversão de pontos."
    buttons = [[create_button("🔙 VOLTAR", "menu:affiliates")]]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard)
    await callback.answer()
