"""
Modelos de afiliados, indicações e pontos.

Representam o relacionamento de indicação entre usuários, as comissões
geradas e os pontos acumulados por cada afiliado.
Todos os valores monetários são armazenados em centavos (inteiro).
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import FullAuditMixin


class Referral(FullAuditMixin):
    """
    Registro de indicação de um usuário por outro.
    """

    __tablename__ = "referrals"
    __table_args__ = (
        UniqueConstraint("tenant_id", "referred_user_id", name="uq_referrals_tenant_referred"),
    )

    # Tenant
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant = relationship("Tenant", back_populates="referrals")

    # Usuário que indicou (afiliado)
    referrer_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    referrer_user = relationship("User", foreign_keys=[referrer_user_id], back_populates="referrals_made")

    # Usuário indicado
    referred_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    referred_user = relationship("User", foreign_keys=[referred_user_id], back_populates="referred_by")

    # Código usado na indicação (opcional, para rastreamento)
    referral_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    def __repr__(self) -> str:
        return f"<Referral(id={self.id}, referrer={self.referrer_user_id}, referred={self.referred_user_id})>"


class AffiliateCommission(FullAuditMixin):
    """
    Comissão gerada para um afiliado a partir de uma recarga/compra do indicado.
    """

    __tablename__ = "affiliate_commissions"

    # Tenant
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant = relationship("Tenant", back_populates="affiliate_commissions")

    # Usuário afiliado que recebe a comissão
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user = relationship("User", back_populates="affiliate_commissions")

    # Usuário que gerou a comissão (indicado)
    source_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Valor da comissão em centavos
    amount_cents: Mapped[int] = mapped_column(Numeric(12, 0), nullable=False)

    # Tipo de origem da comissão (deposit, purchase, etc.)
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)

    # Referência de idempotência para evitar duplicidade
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)

    # Status (PENDING, PAID, CANCELLED)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")

    def __repr__(self) -> str:
        return f"<AffiliateCommission(id={self.id}, user_id={self.user_id}, amount={self.amount_cents})>"


class AffiliatePoints(FullAuditMixin):
    """
    Pontos de indicação acumulados por um usuário.
    """

    __tablename__ = "affiliate_points"

    # Tenant
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant = relationship("Tenant", back_populates="affiliate_points")

    # Usuário (afiliado)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user = relationship("User", back_populates="affiliate_points")

    # Saldo de pontos disponíveis
    points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Total de pontos já convertidos
    total_converted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<AffiliatePoints(id={self.id}, user_id={self.user_id}, points={self.points})>"
