"""
Handlers de checkout e compra.

Fluxo:
- Usuário clica em COMPRAR em um produto (callback catalog:buy)
- Bot mostra detalhes e pergunta quantidade (FSM)
- Calcula total e verifica saldo
- Se saldo suficiente, pergunta método de entrega (Telegram, WhatsApp, e-mail)
- Finaliza compra usando purchase_service
- Se saldo insuficiente, oferece gerar Pix
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
from bot.core.utils import cents_to_brl
from bot.keyboards.utils import create_button
from bot.models.product import Product
from bot.models.user import User
from bot.services.user_service import get_tenant_for_bot, get_or_create_user
from bot.services.purchase_service import purchase_product
from bot.services.wallet_service import get_balance

logger = logging.getLogger(__name__)

router = Router()


class CheckoutStates(StatesGroup):
    WAITING_QUANTITY = State()
    WAITING_DELIVERY_METHOD = State()


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


async def _edit_or_answer(callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup):
    """Edita a mensagem atual, se possível."""
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("catalog:buy:"))
async def buy_product(callback: CallbackQuery, state: FSMContext):
    """
    Inicia o fluxo de compra: mostra produto e pergunta quantidade.
    """
    product_id_str = callback.data.split(":")[-1]
    try:
        product_id = UUID(product_id_str)
    except ValueError:
        await callback.answer("Produto inválido.")
        return

    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        product = (await session.execute(
            select(Product).where(
                Product.id == product_id,
                Product.tenant_id == tenant.id,
                Product.is_active == True,
                Product.deleted_at.is_(None),
            )
        )).scalar_one_or_none()
        if product is None:
            await callback.answer("Produto não encontrado.")
            return

        balance_cents = await get_balance(session, tenant.id, user.id)

    text = (
        f"🛒 <b>{product.name}</b>\n\n"
        f"💵 Preço unitário: {cents_to_brl(int(product.price_cents))}\n"
        f"💰 Seu saldo: {cents_to_brl(balance_cents)}\n\n"
        "📦 Quantos deseja comprar?\n"
        "Digite a quantidade (apenas números)."
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", f"catalog:product:{product.id}")]]
    )

    await state.update_data(product_id=str(product.id), product_price_cents=int(product.price_cents))
    await state.set_state(CheckoutStates.WAITING_QUANTITY)
    await _edit_or_answer(callback, text, keyboard)


@router.message(CheckoutStates.WAITING_QUANTITY)
async def process_quantity(message: Message, state: FSMContext):
    """
    Processa quantidade informada e avança para escolha de entrega ou saldo.
    """
    text_qty = message.text.strip() if message.text else ""
    if not text_qty.isdigit() or int(text_qty) < 1:
        await message.answer("❌ Quantidade inválida. Digite um número inteiro positivo.")
        return

    quantity = int(text_qty)
    data = await state.get_data()
    product_id = UUID(data["product_id"])
    unit_price = data["product_price_cents"]
    total_cents = unit_price * quantity

    tenant, user = await _get_tenant_and_user_from_message(message)
    if tenant is None:
        await message.answer("Sistema indisponível.")
        await state.clear()
        return

    async with get_async_session_factory() as session:
        balance_cents = await get_balance(session, tenant.id, user.id)

    if balance_cents < total_cents:
        # Saldo insuficiente -> oferece Pix
        missing = total_cents - balance_cents
        text = (
            "❌ Saldo insuficiente!\n"
            f"💰 Seu saldo: {cents_to_brl(balance_cents)}\n"
            f"💵 Valor total: {cents_to_brl(total_cents)}\n"
            f"📉 Faltam: {cents_to_brl(missing)}\n\n"
            "Deseja gerar um Pix para completar a compra?"
        )
        buttons = [
            [create_button(f"💠 GERAR PIX {cents_to_brl(missing)}", f"recharge:pix")],  # leva para recarga
            [create_button("❌ CANCELAR", f"catalog:product:{product_id}")],
        ]
        await state.clear()
        await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        return

    # Saldo suficiente -> pergunta método de entrega
    await state.update_data(quantity=quantity, total_cents=total_cents)
    await state.set_state(CheckoutStates.WAITING_DELIVERY_METHOD)

    text = (
        "✅ Saldo suficiente!\n"
        f"💰 Total: {cents_to_brl(total_cents)}\n\n"
        "Escolha como deseja receber seu produto:"
    )
    buttons = [
        [create_button("📱 Telegram", "checkout:delivery:TELEGRAM")],
        [create_button("💬 WhatsApp", "checkout:delivery:WHATSAPP")],
        [create_button("📧 E-mail", "checkout:delivery:EMAIL")],
        [create_button("🔙 CANCELAR", f"catalog:product:{product_id}")],
    ]
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(CheckoutStates.WAITING_DELIVERY_METHOD, F.data.startswith("checkout:delivery:"))
async def process_delivery_method(callback: CallbackQuery, state: FSMContext):
    """
    Recebe método de entrega e finaliza compra.
    """
    method = callback.data.split(":")[-1]
    data = await state.get_data()
    product_id = UUID(data["product_id"])
    quantity = int(data["quantity"])
    total_cents = int(data["total_cents"])

    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        await state.clear()
        return

    async with get_async_session_factory() as session:
        product = (await session.execute(
            select(Product).where(Product.id == product_id, Product.tenant_id == tenant.id)
        )).scalar_one_or_none()
        if product is None:
            await callback.answer("Produto não encontrado.")
            await state.clear()
            return

        # Executa compra real
        result = await purchase_product(
            session=session,
            tenant_id=tenant.id,
            user=user,
            product=product,
            quantity=quantity,
            delivery_method=method,
            bot=callback.bot,
        )

    if result["status"] == "COMPLETED":
        text = (
            "🎉 Compra realizada com sucesso!\n\n"
            f"🎫 Pedido: {result['order_id']}\n"
            f"💰 Total: {cents_to_brl(result['total_cents'])}\n"
            f"📦 Itens vendidos: {result['items_sold']}\n"
            "🔐 Verifique sua entrega (Telegram, WhatsApp ou e-mail conforme escolhido)."
        )
        buttons = [[create_button("🔙 VOLTAR", "menu:back")]]
    else:
        text = f"❌ Falha na compra: {result.get('message', 'Erro desconhecido.')}"
        buttons = [[create_button("🔙 VOLTAR", f"catalog:product:{product_id}")]]

    await state.clear()
    await _edit_or_answer(callback, text, InlineKeyboardMarkup(inline_keyboard=buttons))
