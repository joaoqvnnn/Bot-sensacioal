"""
Website de ativação e consulta de produtos.

Endpoints:
- POST /api/activate  -> ativa produto usando token e senha
- GET  /api/orders/{order_id} -> consulta pedido (com token válido)
- GET  /health -> health check

Usa FastAPI e SQLAlchemy async.
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy import select

from bot.core.config import settings
from bot.core.database import get_async_session_factory
from bot.core.security import verify_password, hash_password
from bot.models.product_access_token import ProductAccessToken
from bot.models.order import Order, OrderItem
from bot.models.inventory_item import InventoryItem
from bot.models.user import User
from bot.models.tenant import Tenant

logger = logging.getLogger(__name__)

app = FastAPI(title="Larizinha Store Website", version="0.1.0")


# ----------------------------------------------------------------------
# Schemas
# ----------------------------------------------------------------------

class ActivateRequest(BaseModel):
    token: str
    password: str


class ActivateResponse(BaseModel):
    status: str
    message: str
    order_id: Optional[UUID] = None
    product_name: Optional[str] = None


class OrderResponse(BaseModel):
    order_id: UUID
    status: str
    total_cents: int
    items: list


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

async def _get_tenant_from_header(bot_username: Optional[str] = Header(None)):
    """Obtém tenant pelo username do bot ou primeiro ativo."""
    from bot.services.user_service import get_tenant_for_bot
    async with get_async_session_factory() as session:
        if bot_username:
            tenant = await get_tenant_for_bot(session, bot_username)
            if tenant:
                return tenant
        stmt = select(Tenant).where(
            Tenant.is_active == True,
            Tenant.deleted_at.is_(None),
        ).order_by(Tenant.created_at.asc())
        result = await session.execute(stmt)
        return result.scalars().first()


async def _get_valid_token(session, tenant_id: UUID, token_str: str) -> Optional[ProductAccessToken]:
    """
    Busca token válido (não expirado, não usado, status ACTIVE) pelo hash.
    """
    from bot.core.security import hash_password  # não; usar hash sha256
    import hashlib
    token_hash = hashlib.sha256(token_str.encode("utf-8")).hexdigest()

    stmt = select(ProductAccessToken).where(
        ProductAccessToken.tenant_id == tenant_id,
        ProductAccessToken.token_hash == token_hash,
        ProductAccessToken.status == "ACTIVE",
        ProductAccessToken.expires_at > datetime.now(timezone.utc),
        ProductAccessToken.deleted_at.is_(None),
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


# ----------------------------------------------------------------------
# Endpoints
# ----------------------------------------------------------------------

@app.get("/health")
async def health():
    """Health check do website."""
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


@app.post("/api/activate", response_model=ActivateResponse)
async def activate_product(request: ActivateRequest, bot_username: Optional[str] = Header(None)):
    """
    Ativa um produto usando token temporário e senha.

    Fluxo:
    1. Busca token válido
    2. Verifica senha do usuário (hash)
    3. Marca token como USED
    4. Retorna detalhes do pedido/produto

    Args:
        request: Token e senha.
        bot_username: Username do bot.

    Returns:
        ActivateResponse: Resultado da ativação.
    """
    tenant = await _get_tenant_from_header(bot_username)
    if tenant is None:
        raise HTTPException(status_code=503, detail="Sistema indisponível.")

    async with get_async_session_factory() as session:
        token = await _get_valid_token(session, tenant.id, request.token)
        if token is None:
            raise HTTPException(status_code=400, detail="Token inválido ou expirado.")

        # Obtém usuário associado ao pedido
        order = (await session.execute(
            select(Order).where(Order.id == token.order_id)
        )).scalar_one_or_none()
        if order is None:
            raise HTTPException(status_code=404, detail="Pedido não encontrado.")

        user = (await session.execute(
            select(User).where(User.id == order.user_id)
        )).scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=404, detail="Usuário não encontrado.")

        # Verifica senha
        if not user.password_hash:
            raise HTTPException(status_code=400, detail="Senha não cadastrada para este usuário.")

        if not verify_password(request.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Senha incorreta.")

        # Marca token como usado
        token.status = "USED"
        token.used_at = datetime.now(timezone.utc)
        await session.commit()

        # Busca primeiro item do pedido para retornar nome do produto
        order_item = (await session.execute(
            select(OrderItem).where(OrderItem.order_id == order.id).limit(1)
        )).scalar_one_or_none()
        product_name = order_item.product_name if order_item else None

        return ActivateResponse(
            status="SUCCESS",
            message="Produto ativado com sucesso.",
            order_id=order.id,
            product_name=product_name,
        )


@app.get("/api/orders/{order_id}", response_model=OrderResponse)
async def get_order(order_id: UUID, token: str = Header(...), bot_username: Optional[str] = Header(None)):
    """
    Consulta um pedido usando token de acesso válido.

    Args:
        order_id: ID do pedido.
        token: Token de acesso enviado no header.
        bot_username: Username do bot.

    Returns:
        OrderResponse: Detalhes do pedido.
    """
    tenant = await _get_tenant_from_header(bot_username)
    if tenant is None:
        raise HTTPException(status_code=503, detail="Sistema indisponível.")

    async with get_async_session_factory() as session:
        token_obj = await _get_valid_token(session, tenant.id, token)
        if token_obj is None:
            raise HTTPException(status_code=401, detail="Token inválido ou expirado.")

        # Verifica se o token pertence a este pedido
        if token_obj.order_id != order_id:
            raise HTTPException(status_code=403, detail="Token não autorizado para este pedido.")

        order = (await session.execute(
            select(Order).where(Order.id == order_id)
        )).scalar_one_or_none()
        if order is None:
            raise HTTPException(status_code=404, detail="Pedido não encontrado.")

        items = []
        order_items = (await session.execute(
            select(OrderItem).where(OrderItem.order_id == order_id)
        )).scalars().all()
        for item in order_items:
            items.append({
                "product_id": str(item.product_id),
                "product_name": item.product_name,
                "quantity": item.quantity,
                "unit_price_cents": int(item.unit_price_cents),
            })

        return OrderResponse(
            order_id=order.id,
            status=order.status,
            total_cents=int(order.total_cents),
            items=items,
        )
