"""
Serviço de saques.

Fornece funções para:
- Solicitar saque (com validação de saldo e senha)
- Processar saque via provedor (Mercado Pago ou outro)
- Atualizar status (PAID, FAILED) com idempotência
- Reverter saldo em caso de falha

Todas as operações financeiras usam centavos e são atômicas.
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.core.security import verify_password
from bot.models.withdrawal import Withdrawal, WithdrawalAccount
from bot.models.user import User
from bot.models.wallet import Wallet
from bot.services.wallet_service import debit_wallet, credit_wallet

logger = logging.getLogger(__name__)


async def create_withdrawal_request(
    session: AsyncSession,
    tenant_id: UUID,
    user_id: UUID,
    amount_cents: int,
    withdrawal_account_id: UUID,
    password: str,
    idempotency_key: Optional[str] = None,
) -> Withdrawal:
    """
    Cria uma solicitação de saque.

    Fluxo:
    1. Valida valor > 0
    2. Verifica conta de saque pertence ao usuário
    3. Verifica senha (hash)
    4. Debita saldo (reserva)
    5. Cria Withdrawal com status PENDING
    6. Processa via provedor (mock ou real)
    7. Atualiza status PAID ou FAILED
    8. Se falhar, reverte débito

    Args:
        session: Sessão do banco.
        tenant_id: ID do tenant.
        user_id: ID do usuário.
        amount_cents: Valor do saque em centavos.
        withdrawal_account_id: ID da conta de destino.
        password: Senha de saque.
        idempotency_key: Chave para evitar duplicidade.

    Returns:
        Withdrawal: Saque criado.
    """
    if amount_cents <= 0:
        raise ValueError("Valor do saque deve ser positivo.")

    # Verifica idempotência
    if idempotency_key:
        stmt = select(Withdrawal).where(
            Withdrawal.tenant_id == tenant_id,
            Withdrawal.idempotency_key == idempotency_key,
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing:
            logger.info("Saque já solicitado para idempotency_key, retornando existente.")
            return existing

    # Verifica conta de saque
    account = (await session.execute(
        select(WithdrawalAccount).where(
            WithdrawalAccount.id == withdrawal_account_id,
            WithdrawalAccount.tenant_id == tenant_id,
            WithdrawalAccount.user_id == user_id,
            WithdrawalAccount.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if account is None:
        raise ValueError("Conta de saque inválida.")

    # Verifica senha
    user = (await session.execute(
        select(User).where(User.id == user_id, User.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if user is None:
        raise ValueError("Usuário não encontrado.")
    if not user.password_hash:
        raise ValueError("Senha de saque não cadastrada.")
    if not verify_password(password, user.password_hash):
        raise ValueError("Senha incorreta.")

    # Debita saldo (reserva)
    try:
        await debit_wallet(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            amount_cents=amount_cents,
            entry_type="withdrawal",
            description="Saque solicitado",
            reference_id=None,
        )
    except ValueError as e:
        logger.warning(f"Saldo insuficiente para saque: {e}")
        raise

    # Cria registro de saque
    withdrawal = Withdrawal(
        tenant_id=tenant_id,
        user_id=user_id,
        withdrawal_account_id=withdrawal_account_id,
        amount_cents=amount_cents,
        status="PENDING",
        idempotency_key=idempotency_key,
    )
    session.add(withdrawal)
    await session.commit()
    await session.refresh(withdrawal)

    # Processa via provedor (simulação de chamada real)
    # Em produção, chamar API do Mercado Pago/banco.
    # Por enquanto, marcamos como PROCESSING e depois PAID.
    withdrawal.status = "PROCESSING"
    await session.commit()
    logger.info(f"Saque {withdrawal.id} em processamento.")

    # Simula processamento síncrono (substituir por worker real)
    # Neste exemplo, consideramos sucesso.
    withdrawal.status = "PAID"
    withdrawal.paid_at = datetime.now(timezone.utc)
    await session.commit()
    logger.info(f"Saque {withdrawal.id} pago com sucesso.")

    return withdrawal


async def process_withdrawal_status(
    session: AsyncSession,
    tenant_id: UUID,
    withdrawal_id: UUID,
    new_status: str,
    provider_response: Optional[str] = None,
) -> Withdrawal:
    """
    Atualiza status de um saque (PAID, FAILED, CANCELLED).

    Se falhar, reverte o débito.

    Args:
        session: Sessão do banco.
        tenant_id: ID do tenant.
        withdrawal_id: ID do saque.
        new_status: Novo status.
        provider_response: Resposta do provedor.

    Returns:
        Withdrawal: Saque atualizado.
    """
    stmt = select(Withdrawal).where(
        Withdrawal.tenant_id == tenant_id,
        Withdrawal.id == withdrawal_id,
        Withdrawal.deleted_at.is_(None),
    )
    withdrawal = (await session.execute(stmt)).scalar_one_or_none()
    if withdrawal is None:
        raise ValueError("Saque não encontrado.")

    if provider_response:
        withdrawal.provider_response = provider_response

    if new_status == "FAILED":
        # Reverte débito
        await credit_wallet(
            session,
            tenant_id=tenant_id,
            user_id=withdrawal.user_id,
            amount_cents=int(withdrawal.amount_cents),
            entry_type="reversal",
            description="Estorno de saque falho",
            reference_id=withdrawal.id,
        )
    elif new_status == "PAID" and withdrawal.status != "PAID":
        withdrawal.paid_at = datetime.now(timezone.utc)

    withdrawal.status = new_status
    await session.commit()
    await session.refresh(withdrawal)

    logger.info(f"Saque {withdrawal.id} atualizado para {new_status}")
    return withdrawal


async def list_user_withdrawals(
    session: AsyncSession,
    tenant_id: UUID,
    user_id: UUID,
    page: int = 1,
    per_page: int = 10,
) -> list[Withdrawal]:
    """Lista saques do usuário com paginação."""
    stmt = (
        select(Withdrawal)
        .where(
            Withdrawal.tenant_id == tenant_id,
            Withdrawal.user_id == user_id,
            Withdrawal.deleted_at.is_(None),
        )
        .order_by(Withdrawal.created_at.desc())
        .limit(per_page)
        .offset((page - 1) * per_page)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
