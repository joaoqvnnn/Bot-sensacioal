"""
Serviço de carteira e ledger financeiro.

Fornece funções para obter saldo, creditar, debitar e registrar
movimentações no ledger com transações atômicas e validações.
"""

import logging
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.wallet import Wallet, WalletLedger
from bot.models.user import User
from bot.models.tenant import Tenant

logger = logging.getLogger(__name__)


async def get_or_create_wallet(
    session: AsyncSession,
    tenant_id: UUID,
    user_id: UUID,
) -> Wallet:
    """
    Obtém ou cria a carteira de um usuário.

    Args:
        session: Sessão do banco.
        tenant_id: ID do tenant.
        user_id: ID do usuário.

    Returns:
        Wallet: Carteira existente ou recém-criada.
    """
    stmt = select(Wallet).where(
        Wallet.tenant_id == tenant_id,
        Wallet.user_id == user_id,
        Wallet.deleted_at.is_(None),
    )
    result = await session.execute(stmt)
    wallet = result.scalar_one_or_none()

    if wallet is None:
        wallet = Wallet(
            tenant_id=tenant_id,
            user_id=user_id,
            balance_cents=0,
        )
        session.add(wallet)
        await session.commit()
        await session.refresh(wallet)
        logger.info(f"Nova carteira criada para user_id={user_id}, tenant_id={tenant_id}")

    return wallet


async def get_wallet(
    session: AsyncSession,
    tenant_id: UUID,
    user_id: UUID,
) -> Optional[Wallet]:
    """
    Obtém a carteira de um usuário, sem criar.

    Args:
        session: Sessão do banco.
        tenant_id: ID do tenant.
        user_id: ID do usuário.

    Returns:
        Optional[Wallet]: Carteira ou None se não existir.
    """
    stmt = select(Wallet).where(
        Wallet.tenant_id == tenant_id,
        Wallet.user_id == user_id,
        Wallet.deleted_at.is_(None),
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_balance(
    session: AsyncSession,
    tenant_id: UUID,
    user_id: UUID,
) -> int:
    """
    Retorna o saldo atual em centavos de um usuário.

    Args:
        session: Sessão do banco.
        tenant_id: ID do tenant.
        user_id: ID do usuário.

    Returns:
        int: Saldo em centavos.
    """
    wallet = await get_wallet(session, tenant_id, user_id)
    if wallet is None:
        return 0
    return int(wallet.balance_cents)


async def credit_wallet(
    session: AsyncSession,
    tenant_id: UUID,
    user_id: UUID,
    amount_cents: int,
    entry_type: str,
    description: Optional[str] = None,
    reference_id: Optional[UUID] = None,
) -> WalletLedger:
    """
    Credita um valor na carteira do usuário e registra no ledger.

    Args:
        session: Sessão do banco.
        tenant_id: ID do tenant.
        user_id: ID do usuário.
        amount_cents: Valor positivo em centavos.
        entry_type: Tipo de lançamento (ex: "deposit", "gift", "bonus").
        description: Descrição opcional.
        reference_id: ID externo de referência (ex: payment_id).

    Returns:
        WalletLedger: Registro do ledger criado.
    """
    if amount_cents <= 0:
        raise ValueError("Valor de crédito deve ser positivo.")

    wallet = await get_or_create_wallet(session, tenant_id, user_id)

    # Lock na carteira para evitar corrida
    stmt = select(Wallet).where(
        Wallet.id == wallet.id
    ).with_for_update()
    result = await session.execute(stmt)
    wallet = result.scalar_one()

    balance_before = int(wallet.balance_cents)
    wallet.balance_cents = balance_before + amount_cents

    ledger_entry = WalletLedger(
        tenant_id=tenant_id,
        wallet_id=wallet.id,
        user_id=user_id,
        entry_type=entry_type,
        amount_cents=amount_cents,
        balance_after_cents=int(wallet.balance_cents),
        description=description,
        reference_id=reference_id,
    )
    session.add(ledger_entry)

    await session.commit()
    await session.refresh(wallet)
    await session.refresh(ledger_entry)

    logger.info(
        f"Crédito de {amount_cents} centavos para user_id={user_id}, "
        f"saldo anterior={balance_before}, saldo atual={wallet.balance_cents}"
    )
    return ledger_entry


async def debit_wallet(
    session: AsyncSession,
    tenant_id: UUID,
    user_id: UUID,
    amount_cents: int,
    entry_type: str,
    description: Optional[str] = None,
    reference_id: Optional[UUID] = None,
) -> WalletLedger:
    """
    Debita um valor da carteira do usuário e registra no ledger.

    Args:
        session: Sessão do banco.
        tenant_id: ID do tenant.
        user_id: ID do usuário.
        amount_cents: Valor positivo em centavos.
        entry_type: Tipo de lançamento (ex: "purchase", "withdrawal").
        description: Descrição opcional.
        reference_id: ID externo de referência.

    Returns:
        WalletLedger: Registro do ledger criado.

    Raises:
        ValueError: Se saldo insuficiente.
    """
    if amount_cents <= 0:
        raise ValueError("Valor de débito deve ser positivo.")

    wallet = await get_or_create_wallet(session, tenant_id, user_id)

    # Lock na carteira
    stmt = select(Wallet).where(
        Wallet.id == wallet.id
    ).with_for_update()
    result = await session.execute(stmt)
    wallet = result.scalar_one()

    balance_before = int(wallet.balance_cents)
    if balance_before < amount_cents:
        raise ValueError(
            f"Saldo insuficiente: saldo={balance_before}, necessário={amount_cents}"
        )

    wallet.balance_cents = balance_before - amount_cents

    ledger_entry = WalletLedger(
        tenant_id=tenant_id,
        wallet_id=wallet.id,
        user_id=user_id,
        entry_type=entry_type,
        amount_cents=-amount_cents,  # negativo para débito
        balance_after_cents=int(wallet.balance_cents),
        description=description,
        reference_id=reference_id,
    )
    session.add(ledger_entry)

    await session.commit()
    await session.refresh(wallet)
    await session.refresh(ledger_entry)

    logger.info(
        f"Débito de {amount_cents} centavos para user_id={user_id}, "
        f"saldo anterior={balance_before}, saldo atual={wallet.balance_cents}"
    )
    return ledger_entry


async def list_ledger_entries(
    session: AsyncSession,
    wallet_id: UUID,
    page: int = 1,
    per_page: int = 10,
) -> List[WalletLedger]:
    """
    Lista os lançamentos do ledger de uma carteira com paginação.

    Args:
        session: Sessão do banco.
        wallet_id: ID da carteira.
        page: Página (1-indexada).
        per_page: Itens por página.

    Returns:
        List[WalletLedger]: Lançamentos da página.
    """
    offset = (page - 1) * per_page
    stmt = (
        select(WalletLedger)
        .where(WalletLedger.wallet_id == wallet_id)
        .order_by(WalletLedger.created_at.desc())
        .limit(per_page)
        .offset(offset)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
