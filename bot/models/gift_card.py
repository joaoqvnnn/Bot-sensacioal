"""
Modelos de Gift Card e resgate.

Representam códigos de gift card que podem ser resgatados por usuários
para adicionar saldo. O código é armazenado como hash para segurança,
e o resgate é controlado com idempotência.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import FullAuditMixin


class GiftCard(FullAuditMixin):
    """
    Entidade de gift card com valor e código seguro.
    """

    __tablename__ = "gift_cards"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code_hash", name="uq_giftcards_tenant_code_hash"),
    )

    # Tenant
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant = relationship("Tenant", back_populates="gift_cards")

    # Hash do código (nunca armazenamos o código em texto puro)
    code_hash: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    # Valor do gift card em centavos
    amount_cents: Mapped[int] = mapped_column(Numeric(12, 0), nullable=False)

    # Status do gift card
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    # Valores: ACTIVE, RESERVED, REDEEMED, EXPIRED

    # Data de expiração (opcional)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Usuário que resgatou (preenchido no resgate)
    redeemed_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    redeemed_by_user = relationship("User", foreign_keys=[redeemed_by_user_id])

    # Data do resgate
    redeemed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<GiftCard(id={self.id}, status={self.status}, amount={self.amount_cents})>"


class GiftCardRedemption(FullAuditMixin):
    """
    Registro de resgate de um gift card por um usuário.
    """

    __tablename__ = "gift_card_redemptions"

    # Tenant
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant = relationship("Tenant", back_populates="gift_card_redemptions")

    # Gift card resgatado
    gift_card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("gift_cards.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    gift_card = relationship("GiftCard", back_populates="redemptions")

    # Usuário que resgatou
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user = relationship("User", back_populates="gift_card_redemptions")

    # Valor resgatado em centavos
    amount_cents: Mapped[int] = mapped_column(Numeric(12, 0), nullable=False)

    # Chave de idempotência para evitar resgate duplicado
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)

    def __repr__(self) -> str:
        return f"<GiftCardRedemption(id={self.id}, gift_card_id={self.gift_card_id}, user_id={self.user_id})>"
