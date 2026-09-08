"""
Handlers de catálogo de produtos.

Permite navegar por categorias, listar produtos, ver detalhes e
iniciar compra, tudo editando a mesma mensagem (regra de uma única mensagem).
Cada tela possui botão de voltar.
"""

import logging
from typing import Optional
from uuid import UUID

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext

from bot.core.database import get_async_session_factory
from bot.core.utils import cents_to_brl
from bot.keyboards.utils import create_button, add_back_button
from bot.services.catalog_service import (
    list_categories,
    list_products_by_category,
    get_product_with_stock_info,
)
from bot.services.user_service import get_tenant_for_bot, get_or_create_user
from bot.services.wallet_service import get_balance

logger = logging.getLogger(__name__)

router = Router()


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
    """
    Edita a mensagem atual se possível, caso contrário envia uma nova.
    Respeita a regra de mensagem única, editando a mensagem do callback.
    """
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "menu:catalog")
async def show_categories(callback: CallbackQuery, state: FSMContext):
    """
    Exibe a lista de categorias disponíveis.
    """
    tenant, user = await _get_tenant_and_user(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        categories = await list_categories(session, tenant.id)
        balance_cents = await get_balance(session, tenant.id, user.id)

    if not categories:
        text = "📦 Nenhuma categoria disponível no momento."
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[create_button("🔙 VOLTAR", "menu:back")]]
        )
        await _edit_or_answer(callback, text, keyboard)
        return

    text = (
        "📱 Lari Contas | Catálogo de Serviços\n"
        "🔗🔗🔗🔗🔗🔗🔗🔗🔗🔗🔗\n"
        f"💰| Saldo da Carteira: {cents_to_brl(balance_cents)}\n"
        "⬇️ Selecione uma categoria abaixo para ver nossos planos:"
    )

    buttons = []
    for cat in categories:
        buttons.append([create_button(cat.name, f"catalog:category:{cat.id}")])
    buttons.append([create_button("🔙 VOLTAR", "menu:back")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data.startswith("catalog:category:"))
async def show_products(callback: CallbackQuery, state: FSMContext):
    """
    Exibe os produtos de uma categoria selecionada.
    """
    category_id = callback.data.split(":")[-1]
    tenant, user = await _get_tenant_and_user(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        products = await list_products_by_category(session, tenant.id, UUID(category_id))
        balance_cents = await get_balance(session, tenant.id, user.id)

    if not products:
        text = "📦 Nenhum produto disponível nesta categoria."
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [create_button("🔙 VOLTAR", "menu:catalog")],
            ]
        )
        await _edit_or_answer(callback, text, keyboard)
        return

    text = f"💰 Saldo: {cents_to_brl(balance_cents)}\n\nEscolha um produto:"
    buttons = []
    for product in products:
        buttons.append([create_button(
            f"{product.name} — {cents_to_brl(product.price_cents)}",
            f"catalog:product:{product.id}"
        )])
    buttons.append([create_button("🔙 VOLTAR", "menu:catalog")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data.startswith("catalog:product:"))
async def show_product_details(callback: CallbackQuery, state: FSMContext):
    """
    Exibe os detalhes de um produto.
    """
    product_id = callback.data.split(":")[-1]
    tenant, user = await _get_tenant_and_user(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        product_info = await get_product_with_stock_info(session, tenant.id, UUID(product_id))
        balance_cents = await get_balance(session, tenant.id, user.id)

    if product_info is None:
        text = "Produto não encontrado."
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[create_button("🔙 VOLTAR", "menu:catalog")]]
        )
        await _edit_or_answer(callback, text, keyboard)
        return

    # Monta detalhes
    stock = product_info["available_stock"]
    if stock <= 0:
        stock_text = "🔴 Sem estoque"
    else:
        stock_text = f"🟢 Disponível: {stock} unidade(s)"

    text = (
        f"🚀 <b>{product_info['name']}</b>\n"
        f"{stock_text}\n"
        f"├ 💵 Preço: {cents_to_brl(product_info['price_cents'])}\n"
        f"├ 💰 Seu Saldo: {cents_to_brl(balance_cents)}\n"
        f"└ 📦 Estoque: {stock}\n\n"
        f"📝 Descrição:\n{product_info['description'] or 'Sem descrição.'}\n"
        f"🛡 Garantia: {product_info['guarantee_days']} dias\n"
        f"⏳ Duração: {product_info['duration_days']} dias\n"
    )

    buttons = []
    if stock > 0:
        buttons.append([create_button("💳 COMPRAR", f"catalog:buy:{product_info['id']}")])
    buttons.append([create_button("🔙 VOLTAR", f"catalog:category:{callback.data.split(':')[2]}")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data.startswith("catalog:buy:"))
async def buy_product(callback: CallbackQuery, state: FSMContext):
    """
    Inicia o fluxo de compra (ainda simplificado, sem quantidade múltipla).
    """
    product_id = callback.data.split(":")[-1]
    tenant, user = await _get_tenant_and_user(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    # Aqui futuramente chamaremos o purchase_service.purchase_product
    # Por enquanto, apenas mostra mensagem de que a compra será implementada.
    text = "🛒 Em breve: fluxo de compra integrado com estoque e pagamento."
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [create_button("🔙 VOLTAR", f"catalog:product:{product_id}")],
        ]
    )
    await _edit_or_answer(callback, text, keyboard)
