"""
Serviço de afiliados, comissões e pontos.

Fornece funções para:
- Registrar indicação de um usuário por outro
- Criar comissão sobre recargas/compras do indicado
- Acumular pontos de indicação
- Converter pontos em saldo
- Solicitar saque de comissões

Todas as operações financeiras usam centavos e são idempotentes.
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.referral import Referral, AffiliateCommission, AffiliatePoints
from bot.models.affiliate_withdrawal import AffiliateWithdrawal
from bot.models.user import User
from bot.services.wallet_service import credit_wallet

logger = logging.getLogger(__name__)


async def register_referral(
    session: AsyncSession,
    tenant_id: UUID,
    referrer_user_id: UUID,
    referred_user_id: UUID,
    referral_code: Optional[str] = None,
) -> Referral:
    """
    Registra uma indicação entre dois usuários.

    Impede autoindicação e duplicidade.

    Args:
        session: Sessão do banco.
        tenant_id: ID do tenant.
        referrer_user_id: ID do usuário que indicou.
        referred_user_id: ID do usuário indicado.
        referral_code: Código usado (opcional).

    Returns:
        Referral: Registro criado.

    Raises:
        ValueError: Se autoindicação ou indicação duplicada.
    """
    if referrer_user_id == referred_user_id:
        raise ValueError("Autoindicação não permitida.")

    # Verifica se já existe
    stmt = select(Referral).where(
        Referral.tenant_id == tenant_id,
        Referral.referred_user_id == referred_user_id,
        Referral.deleted_at.is_(None),
    )
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing:
        logger.info("Indicação já registrada.")
        return existing

    referral = Referral(
        tenant_id=tenant_id,
        referrer_user_id=referrer_user_id,
        referred_user_id=referred_user_id,
        referral_code=referral_code,
    )
    session.add(referral)
    await session.commit()
    await session.refresh(referral)

    logger.info(
        f"Nova indicação: referrer={referrer_user_id}, referred={referred_user_id}"
    )
    return referral


async def create_commission(
    session: AsyncSession,
    tenant_id: UUID,
    referrer_user_id: UUID,
    source_user_id: UUID,
    amount_cents: int,
    source_type: str,
    idempotency_key: Optional[str] = None,
) -> Optional[AffiliateCommission]:
    """
    Cria uma comissão para o afiliado.

    Se idempotency_key for fornecida e já existir, ignora.

    Args:
        session: Sessão do banco.
        tenant_id: ID do tenant.
        referrer_user_id: ID do afiliado que recebe.
        source_user_id: ID do usuário que gerou a comissão.
        amount_cents: Valor da comissão em centavos.
        source_type: Tipo de origem (deposit, purchase).
        idempotency_key: Chave para evitar duplicidade.

    Returns:
        Optional[AffiliateCommission]: Comissão criada ou None se duplicada.
    """
    if amount_cents <= 0:
        return None

    # Verifica idempotência
    if idempotency_key:
        stmt = select(AffiliateCommission).where(
            AffiliateCommission.tenant_id == tenant_id,
            AffiliateCommission.idempotency_key == idempotency_key,
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing:
            logger.info("Comissão já existente para idempotency_key, ignorando.")
            return None

    commission = AffiliateCommission(
        tenant_id=tenant_id,
        user_id=referrer_user_id,
        source_user_id=source_user_id,
        amount_cents=amount_cents,
        source_type=source_type,
        idempotency_key=idempotency_key,
        status="PENDING",
    )
    session.add(commission)
    await session.commit()
    await session.refresh(commission)

    logger.info(f"Comissão criada: user_id={referrer_user_id}, amount={amount_cents}")
    return commission


async def add_affiliate_points(
    session: AsyncSession,
    tenant_id: UUID,
    user_id: UUID,
    points: int,
) -> AffiliatePoints:
    """
    Adiciona pontos de indicação a um usuário.

    Args:
        session: Sessão do banco.
        tenant_id: ID do tenant.
        user_id: ID do usuário.
        points: Quantidade de pontos (positivo).

    Returns:
        AffiliatePoints: Saldo de pontos atualizado.
    """
    if points <= 0:
        raise ValueError("Pontos devem ser positivos.")

    # Obtém ou cria registro de pontos
    stmt = select(AffiliatePoints).where(
        AffiliatePoints.tenant_id == tenant_id,
        AffiliatePoints.user_id == user_id,
        AffiliatePoints.deleted_at.is_(None),
    )
    result = await session.execute(stmt)
    affiliate_points = result.scalar_one_or_none()

    if affiliate_points is None:
        affiliate_points = AffiliatePoints(
            tenant_id=tenant_id,
            user_id=user_id,
            points=points,
            total_converted=0,
        )
        session.add(affiliate_points)
    else:
        affiliate_points.points += points

    await session.commit()
    await session.refresh(affiliate_points)
    logger.info(f"Adicionados {points} pontos para user_id={user_id}")
    return affiliate_points


async def convert_points_to_balance(
    session: AsyncSession,
    tenant_id: UUID,
    user_id: UUID,
    points_to_convert: int,
    multiplier: float = 0.01,
    min_points: int = 500,
) -> dict:
    """
    Converte pontos de indicação em saldo na carteira.

    Args:
        session: Sessão do banco.
        tenant_id: ID do tenant.
        user_id: ID do usuário.
        points_to_convert: Quantidade de pontos a converter.
        multiplier: Fator de conversão (ex: 0.01 = 1 ponto = R$ 0,01).
        min_points: Pontos mínimos para conversão.

    Returns:
        dict: Resultado com status e valor creditado.
    """
    stmt = select(AffiliatePoints).where(
        AffiliatePoints.tenant_id == tenant_id,
        AffiliatePoints.user_id == user_id,
        AffiliatePoints.deleted_at.is_(None),
    ).with_for_update()
    affiliate_points = (await session.execute(stmt)).scalar_one_or_none()

    if affiliate_points is None or affiliate_points.points < min_points:
        return {"status": "INSUFFICIENT_POINTS", "message": f"Mínimo de {min_points} pontos."}

    if points_to_convert > affiliate_points.points:
        points_to_convert = affiliate_points.points

    amount_cents = int(points_to_convert * multiplier * 100)  # converte para centavos

    if amount_cents <= 0:
        return {"status": "INVALID_AMOUNT", "message": "Valor de conversão inválido."}

    # Debita pontos
    affiliate_points.points -= points_to_convert
    affiliate_points.total_converted += points_to_convert

    # Credita saldo
    await credit_wallet(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        amount_cents=amount_cents,
        entry_type="points_conversion",
        description=f"Conversão de {points_to_convert} pontos",
        reference_id=affiliate_points.id,
    )

    await session.commit()
    logger.info(f"Convertidos {points_to_convert} pontos em {amount_cents} centavos para user_id={user_id}")

    return {"status": "SUCCESS", "amount_cents": amount_cents, "points_converted": points_to_convert}


async def request_withdrawal(
    session: AsyncSession,
    tenant_id: UUID,
    user_id: UUID,
    amount_cents: int,
    withdrawal_account_id: UUID,
    idempotency_key: Optional[str] = None,
) -> AffiliateWithdrawal:
    """
    Cria uma solicitação de saque de comissões.

    Args:
        session: Sessão do banco.
        tenant_id: ID do tenant.
        user_id: ID do usuário afiliado.
        amount_cents: Valor em centavos.
        withdrawal_account_id: ID da conta de saque.
        idempotency_key: Chave de idempotência.

    Returns:
        AffiliateWithdrawal: Saque criado.
    """
    # Verifica idempotência
    if idempotency_key:
        stmt = select(AffiliateWithdrawal).where(
            AffiliateWithdrawal.tenant_id == tenant_id,
            AffiliateWithdrawal.idempotency_key == idempotency_key,
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing:
            logger.info("Saque já solicitado para idempotency_key, retornando existente.")
            return existing

    withdrawal = AffiliateWithdrawal(
        tenant_id=tenant_id,
        user_id=user_id,
        amount_cents=amount_cents,
        withdrawal_account_id=withdrawal_account_id,
        idempotency_key=idempotency_key,
        status="PENDING",
    )
    session.add(withdrawal)
    await session.commit()
    await session.refresh(withdrawal)

    logger.info(f"Solicitação de saque criada: user_id={user_id}, amount={amount_cents}")
    return withdrawal
