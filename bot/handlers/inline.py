"""
Handlers de pesquisa inline de serviços.

Permite ao usuário buscar produtos digitando @username_bot no Telegram.
Retorna resultados reais do banco, com botão COMPRAR que inicia o fluxo
de compra do catálogo, respeitando a regra de mensagem única.
"""

import logging
from typing import List, Optional
from uuid import UUID

from aiogram import F, Router
from aiogram.types import (
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from sqlalchemy import select

from bot.core.database import get_async_session_factory
from bot.core.utils import cents_to_brl
from bot.models.product import Product
from bot.models.tenant import Tenant

logger = logging.getLogger(__name__)

router = Router()


@router.inline_query()
async def inline_search(inline_query: InlineQuery):
    """
    Processa consulta inline e retorna produtos correspondentes.

    Args:
        inline_query: Query inline do Telegram.
    """
    query_text = inline_query.query.strip()
    if not query_text:
        # Se vazio, retorna nada (ou poderia listar todos)
        await inline_query.answer([], cache_time=0)
        return

    async with get_async_session_factory() as session:
        # Obtém tenant com base no bot atual
        tenant = await get_tenant_for_bot(session, inline_query.bot.username)
        if tenant is None:
            await inline_query.answer([], cache_time=0)
            return

        # Busca produtos ativos com nome ou descrição correspondente
        stmt = (
            select(Product)
            .where(
                Product.tenant_id == tenant.id,
                Product.is_active == True,
                Product.deleted_at.is_(None),
                (Product.name.ilike(f"%{query_text}%")) |
                (Product.description.ilike(f"%{query_text}%")),
            )
            .order_by(Product.name.asc())
            .limit(10)
        )
        result = await session.execute(stmt)
        products = list(result.scalars().all())

    # Monta resultados
    results: List[InlineQueryResultArticle] = []
    for product in products:
        # Texto com detalhes
        text = (
            f"🎯 <b>{product.name}</b>\n"
            f"💲 Valor: {cents_to_brl(int(product.price_cents))}\n"
            f"📝 {product.description or 'Sem descrição'}\n"
            f"🛡 Garantia: {product.guarantee_days} dias\n"
            f"⏳ Duração: {product.duration_days} dias"
        )
        # Botão COMPRAR que leva ao fluxo de compra do catálogo
        markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="💳 COMPRAR",
                        callback_data=f"catalog:product:{product.id}",
                    )
                ]
            ]
        )
        results.append(
            InlineQueryResultArticle(
                id=str(product.id),
                title=product.name,
                description=f"{cents_to_brl(int(product.price_cents))}",
                input_message_content=InputTextMessageContent(
                    message_text=text,
                    parse_mode="HTML",
                ),
                reply_markup=markup,
            )
        )

    if not results:
        # Nenhum resultado
        results.append(
            InlineQueryResultArticle(
                id="no_results",
                title="Nenhum serviço encontrado",
                description="Tente outro nome",
                input_message_content=InputTextMessageContent(
                    message_text="Nenhum serviço encontrado.\nTente outro nome."
                ),
            )
        )

    # Responde à consulta inline
    await inline_query.answer(results, cache_time=0)
