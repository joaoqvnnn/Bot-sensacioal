"""
Serviço de catálogo.

Fornece funções para consulta de categorias, produtos e estoque.
Todas as funções são assíncronas e recebem uma sessão do SQLAlchemy.
"""

import logging
from typing import List, Optional
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.category import Category
from bot.models.product import Product
from bot.models.inventory_item import InventoryItem

logger = logging.getLogger(__name__)


async def list_categories(session: AsyncSession, tenant_id) -> List[Category]:
    """
    Lista categorias ativas de um tenant, ordenadas por posição e nome.

    Args:
        session: Sessão do banco.
        tenant_id: ID do tenant.

    Returns:
        List[Category]: Categorias ativas.
    """
    stmt = (
        select(Category)
        .where(
            Category.tenant_id == tenant_id,
            Category.is_active == True,
            Category.deleted_at.is_(None),
        )
        .order_by(Category.position.asc(), Category.name.asc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_products_by_category(
    session: AsyncSession,
    tenant_id,
    category_id,
) -> List[Product]:
    """
    Lista produtos ativos de uma categoria, com contagem de estoque disponível.

    Args:
        session: Sessão do banco.
        tenant_id: ID do tenant.
        category_id: ID da categoria.

    Returns:
        List[Product]: Produtos ativos (sem contagem de estoque, apenas o objeto).
    """
    stmt = (
        select(Product)
        .where(
            Product.tenant_id == tenant_id,
            Product.category_id == category_id,
            Product.is_active == True,
            Product.deleted_at.is_(None),
        )
        .order_by(Product.position.asc(), Product.name.asc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_product_by_id(
    session: AsyncSession,
    tenant_id,
    product_id,
) -> Optional[Product]:
    """
    Obtém um produto pelo ID, se pertencer ao tenant e estiver ativo.

    Args:
        session: Sessão do banco.
        tenant_id: ID do tenant.
        product_id: ID do produto.

    Returns:
        Optional[Product]: Produto encontrado ou None.
    """
    stmt = select(Product).where(
        Product.tenant_id == tenant_id,
        Product.id == product_id,
        Product.is_active == True,
        Product.deleted_at.is_(None),
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_available_stock_count(
    session: AsyncSession,
    tenant_id,
    product_id,
) -> int:
    """
    Retorna a quantidade de itens AVAILABLE (não reservados e não vendidos)
    de um produto.

    Args:
        session: Sessão do banco.
        tenant_id: ID do tenant.
        product_id: ID do produto.

    Returns:
        int: Número de itens disponíveis para venda.
    """
    stmt = (
        select(func.count(InventoryItem.id))
        .where(
            InventoryItem.tenant_id == tenant_id,
            InventoryItem.product_id == product_id,
            InventoryItem.status == "AVAILABLE",
            InventoryItem.deleted_at.is_(None),
        )
    )
    result = await session.execute(stmt)
    return int(result.scalar_one())


async def get_product_with_stock_info(
    session: AsyncSession,
    tenant_id,
    product_id,
) -> Optional[dict]:
    """
    Obtém informações completas do produto para exibição, incluindo
    estoque disponível e dados de preço.

    Args:
        session: Sessão do banco.
        tenant_id: ID do tenant.
        product_id: ID do produto.

    Returns:
        Optional[dict]: Dicionário com dados do produto e estoque, ou None.
    """
    product = await get_product_by_id(session, tenant_id, product_id)
    if product is None:
        return None

    available = await get_available_stock_count(session, tenant_id, product_id)
    return {
        "id": product.id,
        "name": product.name,
        "description": product.description,
        "price_cents": product.price_cents,
        "duration_days": product.duration_days,
        "guarantee_days": product.guarantee_days,
        "available_stock": available,
        "max_per_user": product.max_per_user,
    }
