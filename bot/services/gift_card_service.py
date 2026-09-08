"""
Serviço de Gift Cards.

Fornece funções para:
- Gerar novos gift cards (admin)
- Validar e resgatar gift cards (usuário)
- Hash seguro do código (nunca armazena código puro)
- Atomicidade e idempotência no resgate
"""

import hashlib
import logging
import secrets
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.gift_card import GiftCard, GiftCardRedemption
from bot.models.user import User
from bot.services.wallet_service import credit_wallet

logger = logging.getLogger(__name__)


def _hash_code(code: str) -> str:
    """
    Gera hash SHA-256 do código do gift card.

    Args:
        code: Código em texto puro.

    Returns:
        str: Hash hex.
    """
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


async def generate_gift_cards(
    session: AsyncSession,
    tenant_id: UUID,
    amount_cents: int,
    quantity: int = 1,
    expires_at: Optional[datetime] = None,
) -> List[GiftCard]:
    """
    Gera uma lista de gift cards com códigos aleatórios e valor fixo.

    Args:
        session: Sessão do banco.
        tenant_id: ID do tenant.
        amount_cents: Valor de cada gift card em centavos.
        quantity: Quantidade de cards a gerar.
        expires_at: Data de expiração (opcional).

    Returns:
        List[GiftCard]: Cards criados (com código puro retornado apenas para exibição).
    """
    if amount_cents <= 0:
        raise ValueError("Valor do gift card deve ser positivo.")
    if quantity < 1:
        raise ValueError("Quantidade deve ser pelo menos 1.")

    created_cards = []
    for _ in range(quantity):
        # Gera código aleatório de 16 caracteres (maiúsculas e dígitos)
        code = secrets.token_hex(8).upper()  # 16 caracteres hex
        code_hash = _hash_code(code)
        card = GiftCard(
            tenant_id=tenant_id,
            code_hash=code_hash,
            amount_cents=amount_cents,
            status="ACTIVE",
            expires_at=expires_at,
        )
        session.add(card)
        # Armazenar temporariamente o código puro para devolução
        card._plain_code = code
        created_cards.append(card)

    await session.commit()
    for card in created_cards:
        await session.refresh(card)
        # Não armazenar no banco, apenas em memória para devolver
        card._plain_code = getattr(card, "_plain_code", None)
        logger.info(f"Gift card gerado: id={card.id}, value={card.amount_cents}")

    return created_cards


async def redeem_gift_card(
    session: AsyncSession,
    tenant_id: UUID,
    user: User,
    code: str,
    idempotency_key: Optional[str] = None,
) -> dict:
    """
    Resgata um gift card e credita o valor na carteira do usuário.

    Args:
        session: Sessão do banco.
        tenant_id: ID do tenant.
        user: Usuário que está resgatando.
        code: Código do gift card (texto puro).
        idempotency_key: Chave para evitar resgate duplicado.

    Returns:
        dict: Resultado com status e mensagem.
    """
    code_hash = _hash_code(code)

    # Busca gift card pelo hash
    stmt = select(GiftCard).where(
        GiftCard.tenant_id == tenant_id,
        GiftCard.code_hash == code_hash,
        GiftCard.deleted_at.is_(None),
    )
    result = await session.execute(stmt)
    card = result.scalar_one_or_none()

    if card is None:
        return {"status": "INVALID", "message": "Gift não encontrado."}

    # Verifica se já foi resgatado
    if card.status == "REDEEMED":
        return {"status": "ALREADY_REDEEMED", "message": "Gift já resgatado."}
    if card.status == "EXPIRED":
        return {"status": "EXPIRED", "message": "Gift expirado."}
    if card.expires_at and card.expires_at < datetime.now(timezone.utc):
        # Atualiza status para expirado e retorna
        card.status = "EXPIRED"
        await session.commit()
        return {"status": "EXPIRED", "message": "Gift expirado."}

    # Verifica idempotência: se já houver um resgate com a mesma chave, retorna sucesso
    if idempotency_key:
        stmt_red = select(GiftCardRedemption).where(
            GiftCardRedemption.tenant_id == tenant_id,
            GiftCardRedemption.idempotency_key == idempotency_key,
        )
        existing_red = (await session.execute(stmt_red)).scalar_one_or_none()
        if existing_red:
            logger.info("Resgate já processado para idempotency_key, ignorando.")
            return {"status": "ALREADY_PROCESSED", "message": "Gift já resgatado."}

    # Marca como RESERVED para evitar corrida
    stmt_lock = select(GiftCard).where(
        GiftCard.id == card.id
    ).with_for_update()
    card = (await session.execute(stmt_lock)).scalar_one()

    if card.status != "ACTIVE":
        return {"status": "INVALID", "message": "Gift não disponível."}

    # Atualiza para REDEEMED
    card.status = "REDEEMED"
    card.redeemed_by_user_id = user.id
    card.redeemed_at = datetime.now(timezone.utc)

    # Credita carteira
    await credit_wallet(
        session,
        tenant_id=tenant_id,
        user_id=user.id,
        amount_cents=int(card.amount_cents),
        entry_type="gift",
        description="Resgate de Gift Card",
        reference_id=card.id,
    )

    # Cria registro de resgate
    redemption = GiftCardRedemption(
        tenant_id=tenant_id,
        gift_card_id=card.id,
        user_id=user.id,
        amount_cents=int(card.amount_cents),
        idempotency_key=idempotency_key,
    )
    session.add(redemption)

    await session.commit()
    logger.info(f"Gift card {card.id} resgatado por user_id={user.id}, valor={card.amount_cents}")

    return {"status": "SUCCESS", "message": "Gift Card resgatado!", "amount_cents": int(card.amount_cents)}


async def list_gift_cards(
    session: AsyncSession,
    tenant_id: UUID,
    status: Optional[str] = None,
    page: int = 1,
    per_page: int = 10,
) -> List[GiftCard]:
    """
    Lista gift cards de um tenant, opcionalmente filtrando por status.

    Args:
        session: Sessão do banco.
        tenant_id: ID do tenant.
        status: Filtro de status (ACTIVE, REDEEMED, etc.)
        page: Página (1-indexada).
        per_page: Itens por página.

    Returns:
        List[GiftCard]: Cards da página.
    """
    stmt = select(GiftCard).where(
        GiftCard.tenant_id == tenant_id,
        GiftCard.deleted_at.is_(None),
    )
    if status:
        stmt = stmt.where(GiftCard.status == status)

    stmt = stmt.order_by(GiftCard.created_at.desc()).limit(per_page).offset((page - 1) * per_page)
    result = await session.execute(stmt)
    return list(result.scalars().all())
