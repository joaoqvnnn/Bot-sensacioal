"""
Rotas de carrinho de compras para o Telegram Mini App.

Usa Redis para armazenar o carrinho temporário de cada usuário.
Endpoints:
- POST /api/cart/add
- POST /api/cart/remove
- GET  /api/cart
- POST /api/cart/checkout

Todas as operações consultam dados reais do banco/Redis.
"""

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy import select

from bot.core.config import settings
from bot.core.database import get_async_session_factory
from bot.core.redis import create_redis_client, close_redis_client
from bot.models.product import Product
from bot.models.tenant import Tenant
from bot.models.user import User
from bot.services.user_service import get_tenant_for_bot, get_or_create_user
from bot.services.purchase_service import purchase_product
from bot.core.utils import cents_to_brl

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cart", tags=["cart"])


class CartAddRequest(BaseModel):
    user_id: UUID
    product_id: UUID
    quantity: int = 1


class CartRemoveRequest(BaseModel):
    user_id: UUID
    product_id: UUID


class CartCheckoutRequest(BaseModel):
    user_id: UUID


async def _get_redis():
    """Obtém um cliente Redis (deve ser fechado após uso)."""
    return await create_redis_client(settings)


async def _get_tenant_from_header(bot_username: Optional[str] = Header(None)):
    """Obtém tenant pelo username do bot ou primeiro ativo."""
    async with get_async_session_factory() as session:
        if bot_username:
            tenant = await get_tenant_for_bot(session, bot_username)
            if tenant:
                return tenant
        # fallback: primeiro ativo
        stmt = select(Tenant).where(
            Tenant.is_active == True,
            Tenant.deleted_at.is_(None),
        ).order_by(Tenant.created_at.asc())
        result = await session.execute(stmt)
        return result.scalars().first()


@router.post("/add")
async def add_to_cart(request: CartAddRequest, bot_username: Optional[str] = Header(None)):
    """
    Adiciona um produto ao carrinho do usuário.

    Args:
        request: Dados do produto e quantidade.
        bot_username: Username do bot (para identificar tenant).

    Returns:
        dict: Mensagem de sucesso e quantidade total no carrinho.
    """
    tenant = await _get_tenant_from_header(bot_username)
    if tenant is None:
        raise HTTPException(status_code=503, detail="Sistema indisponível.")

    # Verifica se produto existe e está ativo
    async with get_async_session_factory() as session:
        product = (await session.execute(
            select(Product).where(
                Product.id == request.product_id,
                Product.tenant_id == tenant.id,
                Product.is_active == True,
                Product.deleted_at.is_(None),
            )
        )).scalar_one_or_none()
        if product is None:
            raise HTTPException(status_code=404, detail="Produto não encontrado.")

    # Conecta ao Redis e adiciona ao carrinho
    redis = await _get_redis()
    try:
        cart_key = f"cart:{request.user_id}"
        await redis.hincrby(cart_key, str(request.product_id), request.quantity)
        total_qty = await redis.hget(cart_key, str(request.product_id))
        return {"status": "OK", "message": "Produto adicionado.", "quantity": int(total_qty)}
    except Exception as e:
        logger.exception(f"Erro ao adicionar ao carrinho: {e}")
        raise HTTPException(status_code=500, detail="Erro interno.")
    finally:
        await close_redis_client(redis)


@router.post("/remove")
async def remove_from_cart(request: CartRemoveRequest, bot_username: Optional[str] = Header(None)):
    """
    Remove um produto do carrinho.

    Args:
        request: Dados do usuário e produto.
        bot_username: Username do bot.

    Returns:
        dict: Mensagem de sucesso.
    """
    tenant = await _get_tenant_from_header(bot_username)
    if tenant is None:
        raise HTTPException(status_code=503, detail="Sistema indisponível.")

    redis = await _get_redis()
    try:
        cart_key = f"cart:{request.user_id}"
        await redis.hdel(cart_key, str(request.product_id))
        return {"status": "OK", "message": "Produto removido."}
    except Exception as e:
        logger.exception(f"Erro ao remover do carrinho: {e}")
        raise HTTPException(status_code=500, detail="Erro interno.")
    finally:
        await close_redis_client(redis)


@router.get("")
async def get_cart(user_id: UUID, bot_username: Optional[str] = Header(None)):
    """
    Lista itens do carrinho com detalhes e total.

    Args:
        user_id: ID do usuário.
        bot_username: Username do bot.

    Returns:
        dict: Itens, quantidade, preços e total.
    """
    tenant = await _get_tenant_from_header(bot_username)
    if tenant is None:
        raise HTTPException(status_code=503, detail="Sistema indisponível.")

    redis = await _get_redis()
    try:
        cart_key = f"cart:{user_id}"
        cart_data = await redis.hgetall(cart_key)

        if not cart_data:
            return {"items": [], "total_cents": 0, "total_brl": "R$ 0,00"}

        items = []
        total_cents = 0
        async with get_async_session_factory() as session:
            for product_id_str, qty_str in cart_data.items():
                product_id = UUID(product_id_str)
                quantity = int(qty_str)
                product = (await session.execute(
                    select(Product).where(
                        Product.id == product_id,
                        Product.tenant_id == tenant.id,
                    )
                )).scalar_one_or_none()
                if product:
                    subtotal = int(product.price_cents) * quantity
                    total_cents += subtotal
                    items.append({
                        "product_id": str(product.id),
                        "name": product.name,
                        "quantity": quantity,
                        "unit_price_cents": int(product.price_cents),
                        "subtotal_cents": subtotal,
                    })

        return {
            "items": items,
            "total_cents": total_cents,
            "total_brl": cents_to_brl(total_cents),
        }
    except Exception as e:
        logger.exception(f"Erro ao obter carrinho: {e}")
        raise HTTPException(status_code=500, detail="Erro interno.")
    finally:
        await close_redis_client(redis)


@router.post("/checkout")
async def checkout_cart(request: CartCheckoutRequest, bot_username: Optional[str] = Header(None)):
    """
    Finaliza a compra dos itens do carrinho.

    Args:
        request: Dados do usuário.
        bot_username: Username do bot.

    Returns:
        dict: Resultado da compra.
    """
    tenant = await _get_tenant_from_header(bot_username)
    if tenant is None:
        raise HTTPException(status_code=503, detail="Sistema indisponível.")

    redis = await _get_redis()
    try:
        cart_key = f"cart:{request.user_id}"
        cart_data = await redis.hgetall(cart_key)
        if not cart_data:
            raise HTTPException(status_code=400, detail="Carrinho vazio.")

        async with get_async_session_factory() as session:
            user = (await session.execute(
                select(User).where(User.id == request.user_id, User.tenant_id == tenant.id)
            )).scalar_one_or_none()
            if user is None:
                raise HTTPException(status_code=404, detail="Usuário não encontrado.")

            # Processa cada item do carrinho
            results = []
            for product_id_str, qty_str in cart_data.items():
                product_id = UUID(product_id_str)
                quantity = int(qty_str)
                product = (await session.execute(
                    select(Product).where(Product.id == product_id, Product.tenant_id == tenant.id)
                )).scalar_one_or_none()
                if product is None:
                    results.append({"product_id": str(product_id), "status": "PRODUCT_NOT_FOUND"})
                    continue

                # Tenta compra
                try:
                    result = await purchase_product(
                        session=session,
                        tenant_id=tenant.id,
                        user=user,
                        product=product,
                        quantity=quantity,
                    )
                    results.append({"product_id": str(product_id), "status": result["status"], "detail": result})
                except Exception as e:
                    logger.exception(f"Erro na compra do produto {product_id}: {e}")
                    results.append({"product_id": str(product_id), "status": "FAILED", "detail": str(e)})

            # Limpa carrinho após processar (mesmo com falhas parciais)
            await redis.delete(cart_key)

            return {"status": "PROCESSED", "results": results}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Erro no checkout: {e}")
        raise HTTPException(status_code=500, detail="Erro interno.")
    finally:
        await close_redis_client(redis)
