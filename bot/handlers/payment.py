"""
Handlers de verificação de pagamento.

Permite ao usuário consultar o status de um pagamento Pix gerado,
exibindo se está pendente, pago, expirado, etc. Tudo com edição
da mesma mensagem e botão de voltar.
"""

import logging
from typing import Optional
from uuid import UUID

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext

from bot.core.config import settings
from bot.core.database import get_async_session_factory
from bot.core.utils import cents_to_brl
from bot.keyboards.utils import create_button
from bot.services.user_service import get_tenant_for_bot, get_or_create_user
from bot.services.wallet_service import get_balance
from bot.services.payment_service import get_payment_by_id

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


@router.callback_query(F.data.startswith("payment:check:"))
async def check_payment(callback: CallbackQuery, state: FSMContext):
    """Verifica o status de um pagamento Pix."""
    payment_id_str = callback.data.split(":")[-1]
    try:
        payment_id = UUID(payment_id_str)
    except ValueError:
        await callback.answer("ID de pagamento inválido.")
        return

    tenant, user = await _get_tenant_and_user(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    factory = get_async_session_factory()
    async with factory() as session:
        payment = await get_payment_by_id(
            session=session,
            tenant_id=tenant.id,
            payment_id=payment_id,
        )

        if payment is None or payment.user_id != user.id:
            await callback.answer("Pagamento não encontrado.")
            return

        balance_cents = await get_balance(session, tenant.id, user.id)

    status_emoji = {
        "PENDING": "🟡",
        "PAID": "🟢",
        "EXPIRED": "🔴",
        "FAILED": "🔴",
        "CANCELLED": "⚫",
    }

    emoji = status_emoji.get(payment.status, "⚪")
    text = (
        f"{emoji} Status do Pagamento: {payment.status}\n\n"
        f"🆔 Referência: {payment.id}\n"
        f"💵 Valor: {cents_to_brl(int(payment.amount_cents))}\n"
    )

    if payment.status == "PAID":
        text += f"💰 Seu saldo atual: {cents_to_brl(balance_cents)}\n"
        text += "✅ Pagamento confirmado! O saldo já foi creditado."
    elif payment.status == "PENDING":
        text += "⏳ Aguardando confirmação do pagamento.\n"
        text += "📋 Copie o código Pix e pague para liberar seu saldo."
    elif payment.status == "EXPIRED":
        text += "⌛️ Pagamento expirado. Gere um novo Pix."
    elif payment.status in ("FAILED", "CANCELLED"):
        text += "❌ Pagamento não concluído. Tente novamente."

    buttons = []
    if payment.status == "PENDING" and payment.pix_code:
        buttons.append([create_button("📋 COPIAR PIX", f"payment:copy:{payment.id}")])
    buttons.append([create_button("🔄 VERIFICAR NOVAMENTE", f"payment:check:{payment.id}")])
    buttons.append([create_button("🔙 VOLTAR", "menu:recharge")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("payment:copy:"))
async def copy_pix(callback: CallbackQuery, state: FSMContext):
    """Envia o código Pix copia-e-cola como mensagem separada."""
    payment_id_str = callback.data.split(":")[-1]
    try:
        payment_id = UUID(payment_id_str)
    except ValueError:
        await callback.answer("ID inválido.")
        return

    tenant, user = await _get_tenant_and_user(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    factory = get_async_session_factory()
    async with factory() as session:
        payment = await get_payment_by_id(session, tenant.id, payment_id)
        if payment is None or payment.user_id != user.id:
            await callback.answer("Pagamento não encontrado.")
            return

        if payment.pix_code:
            await callback.message.answer(
                f"💎 Pix Copia e Cola:\n<code>{payment.pix_code}</code>",
                parse_mode="HTML",
            )
        else:
            await callback.message.answer("Código Pix não disponível.")

    await callback.answer()
