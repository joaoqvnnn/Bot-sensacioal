"""
API do Telegram Mini App (FastAPI).

Fornece endpoints para o Mini App do Telegram:
- Validação de initData (autenticação)
- Consulta de saldo e produtos
- Carrinho (futuro)
- Pagamento Pix (futuro)

Todas as respostas usam dados reais do banco.
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Query, Depends
from pydantic import BaseModel
from sqlalchemy import select

from bot.core.config import settings
from bot.core.database import get_async_session_factory
from bot.models.product import Product
from bot.models.user import User
from bot.models.tenant import Tenant
from bot.services.wallet_service import get_balance
from bot.core.utils import cents_to_brl

logger = logging.getLogger(__name__)

app = FastAPI(title="Larizinha Store Mini App", version="0.1.0")


# ----------------------------------------------------------------------
# Schemas
# ----------------------------------------------------------------------

class InitData(BaseModel):
    """Schema para validação de initData do Telegram."""
    init_data: str


class ProductResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    price_cents: int
    duration_days: int
    guarantee_days: int
    available_stock: int


class BalanceResponse(BaseModel):
    user_id: UUID
    balance_cents: int
    balance_brl: str


# ----------------------------------------------------------------------
# Autenticação / Validação de initData
# ----------------------------------------------------------------------

async def validate_init_data(init_data: str) -> Optional[dict]:
    """
    Valida o initData do Telegram WebApp.

    Em produção, deve verificar a assinatura HMAC usando o token do bot.
    Por ora, retornamos os dados parseados; a validação criptográfica
    será implementada em versão futura.

    Args:
        init_data: String initData do WebApp.

    Returns:
        Optional[dict]: Dados decodificados ou None se inválido.
    """
    from urllib.parse import parse_qs

    parsed = parse_qs(init_data)
    # O Telegram envia campos como user, auth_date, hash, etc.
    # Aqui apenas verificamos a presença de user
    if "user" not in parsed:
        return None

    import json
    try:
        user_data = json.loads(parsed["user"][0])
        return user_data
    except Exception:
        return None


# ----------------------------------------------------------------------
# Dependência para obter tenant
# ----------------------------------------------------------------------

async def get_tenant_from_bot_username(bot_username: str) -> Optional[Tenant]:
    """Obtém tenant pelo username do bot."""
    async with get_async_session_factory() as session:
        stmt = select(Tenant).where(
            Tenant.is_active == True,
            Tenant.deleted_at.is_(None),
        )
        result = await session.execute(stmt)
        # Simplificação: retorna primeiro tenant ativo.
        # Em produção, associar pelo username do bot.
        return result.scalars().first()


# ----------------------------------------------------------------------
# Endpoints
# ----------------------------------------------------------------------

@app.get("/health")
async def health():
    """Health check da API."""
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


@app.post("/api/auth", response_model=dict)
async def authenticate(data: InitData):
    """
    Autentica o usuário via initData do Telegram.

    Args:
        data: InitData do WebApp.

    Returns:
        dict: Dados do usuário autenticado e informações da conta.
    """
    user_data = await validate_init_data(data.init_data)
    if not user_data:
        raise HTTPException(status_code=400, detail="initData inválido.")

    telegram_id = user_data.get("id")
    username = user_data.get("username")
    first_name = user_data.get("first_name")
    last_name = user_data.get("last_name")

    if not telegram_id:
        raise HTTPException(status_code=400, detail="ID do usuário ausente.")

    # Obtém tenant (necessário para isolamento)
    # Em produção, usar bot_username do header ou configuração
    tenant = await get_tenant_from_bot_username(None)
    if tenant is None:
        raise HTTPException(status_code=503, detail="Sistema indisponível.")

    async with get_async_session_factory() as session:
        # Obtém ou cria usuário
        from bot.services.user_service import get_or_create_user
        user = await get_or_create_user(
            session=session,
            tenant=tenant,
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
        )

        balance_cents = await get_balance(session, tenant.id, user.id)

    return {
        "user_id": str(user.id),
        "telegram_id": user.telegram_id,
        "username": user.username,
        "first_name": user.first_name,
        "balance_cents": balance_cents,
        "balance_brl": cents_to_brl(balance_cents),
    }


@app.get("/api/products", response_model=list[ProductResponse])
async def list_products():
    """
    Lista produtos ativos com estoque disponível.

    Returns:
        list[ProductResponse]: Lista de produtos.
    """
    tenant = await get_tenant_from_bot_username(None)
    if tenant is None:
        raise HTTPException(status_code=503, detail="Sistema indisponível.")

    async with get_async_session_factory() as session:
        from bot.services.catalog_service import list_categories, list_products_by_category, get_available_stock_count

        # Para simplificar, lista todos os produtos ativos do tenant
        stmt = select(Product).where(
            Product.tenant_id == tenant.id,
            Product.is_active == True,
            Product.deleted_at.is_(None),
        ).order_by(Product.name.asc())
        result = await session.execute(stmt)
        products = list(result.scalars().all())

        response = []
        for product in products:
            stock = await get_available_stock_count(session, tenant.id, product.id)
            response.append(ProductResponse(
                id=product.id,
                name=product.name,
                description=product.description,
                price_cents=int(product.price_cents),
                duration_days=product.duration_days,
                guarantee_days=product.guarantee_days,
                available_stock=stock,
            ))

        return response


@app.get("/api/balance/{user_id}", response_model=BalanceResponse)
async def get_user_balance(user_id: UUID):
    """
    Consulta saldo de um usuário.

    Args:
        user_id: ID do usuário.

    Returns:
        BalanceResponse: Saldo em centavos e formatado.
    """
    tenant = await get_tenant_from_bot_username(None)
    if tenant is None:
        raise HTTPException(status_code=503, detail="Sistema indisponível.")

    async with get_async_session_factory() as session:
        balance_cents = await get_balance(session, tenant.id, user_id)
        return BalanceResponse(
            user_id=user_id,
            balance_cents=balance_cents,
            balance_brl=cents_to_brl(balance_cents),
        )
