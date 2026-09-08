"""
Handlers de alertas de estoque.

Permite ao usuário visualizar produtos e ativar/desativar alertas para ser
notificado quando houver novas unidades. Tudo com edição da mesma mensagem,
paginação e botão de voltar. Nada fictício.
"""

import logging
from typing import List, Optional
from uuid import UUID

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from sqlalchemy import select

from bot.core.database import get_async_session_factory
from bot.keyboards.utils import create_button, create_pagination_buttons
from bot.models.alert import AlertSubscription
from bot.models.product import Product
from bot.services.user_service import get_tenant_for_bot, get_or_create_user

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
    """Edita a mensagem atual, se possível."""
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard)
    await callback.answer()


async def _get_products_with_alert_status(session, tenant_id: UUID, user_id: UUID) -> List[tuple]:
    """
    Retorna lista de produtos e status de alerta do usuário.

    Returns:
        List[tuple]: (Product, bool) onde bool indica se alerta está ativo.
    """
    stmt = (
        select(Product)
        .where(
            Product.tenant_id == tenant_id,
            Product.is_active == True,
            Product.deleted_at.is_(None),
        )
        .order_by(Product.name.asc())
    )
    result = await session.execute(stmt)
    products = list(result.scalars().all())

    # Busca alertas do usuário
    alert_stmt = select(AlertSubscription).where(
        AlertSubscription.tenant_id == tenant_id,
        AlertSubscription.user_id == user_id,
        AlertSubscription.is_active == True,
        AlertSubscription.deleted_at.is_(None),
    )
    alert_result = await session.execute(alert_stmt)
    active_alerts = {alert.product_id for alert in alert_result.scalars().all()}

    return [(product, product.id in active_alerts) for product in products]


@router.callback_query(F.data == "menu:alerts")
async def show_alerts(callback: CallbackQuery, state: FSMContext, page: int = 1):
    """Exibe a lista de produtos com opção de ativar/desativar alertas."""
    tenant, user = await _get_tenant_and_user(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        products_with_status = await _get_products_with_alert_status(session, tenant.id, user.id)

    if not products_with_status:
        text = "📦 Nenhum produto disponível para alertas."
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[create_button("🔙 VOLTAR", "menu:back")]]
        )
        await _edit_or_answer(callback, text, keyboard)
        return

    per_page = 5
    total_pages = max(1, (len(products_with_status) + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    end = start + per_page
    page_items = products_with_status[start:end]

    text = (
        "⚠️ Sistema de /alertas\n"
        "Seja notificado quando seu serviço favorito for abastecido 🤩\n"
        "🎯 Basta selecionar abaixo os serviços que você deseja ser notificado.\n\n"
        "Lista de serviços que você pode ser notificado ⤵️\n"
    )

    buttons = []
    for product, is_active in page_items:
        # Texto do botão com estado
        prefix = "✅" if is_active else "❌"
        # Callback para alternar
        callback_data = f"alerts:toggle:{product.id}:{page}"
        buttons.append([create_button(f"{prefix} {product.name}", callback_data)])

    # Paginação
    nav_buttons = create_pagination_buttons(page, total_pages, "alerts:page")
    if nav_buttons:
        buttons.append(nav_buttons)
    buttons.append([create_button("🔙 VOLTAR", "menu:back")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data.startswith("alerts:page:"))
async def alerts_page_callback(callback: CallbackQuery, state: FSMContext):
    """Trata paginação de alertas."""
    parts = callback.data.split(":")
    if len(parts) == 3 and parts[1] == "page" and parts[2].isdigit():
        page = int(parts[2])
        await show_alerts(callback, state, page)
    else:
        await show_alerts(callback, state)


@router.callback_query(F.data.startswith("alerts:toggle:"))
async def toggle_alert(callback: CallbackQuery, state: FSMContext):
    """Ativa ou desativa alerta para um produto."""
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("Dados inválidos.")
        return

    product_id = UUID(parts[2])
    page = int(parts[3])

    tenant, user = await _get_tenant_and_user(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        # Verifica se já existe alerta ativo
        stmt = select(AlertSubscription).where(
            AlertSubscription.tenant_id == tenant.id,
            AlertSubscription.user_id == user.id,
            AlertSubscription.product_id == product_id,
            AlertSubscription.deleted_at.is_(None),
        )
        alert = (await session.execute(stmt)).scalar_one_or_none()

        if alert:
            # Inverte estado
            alert.is_active = not alert.is_active
            await session.commit()
            action = "ativado" if alert.is_active else "desativado"
        else:
            # Cria novo alerta ativo
            new_alert = AlertSubscription(
                tenant_id=tenant.id,
                user_id=user.id,
                product_id=product_id,
                is_active=True,
            )
            session.add(new_alert)
            await session.commit()
            action = "ativado"

        await callback.answer(f"Alerta {action}!")

    # Reexibe a lista de alertas na mesma página
    await show_alerts(callback, state, page)
