"""
Modelo de saque de afiliado.

Representa uma solicitação de saque feita por um afiliado a partir de suas
comissões acumuladas, com controle de status e idempotência.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import FullAuditMixin


class AffiliateWithdrawal(FullAuditMixin):
    """
    Solicitação de saque de comissões de afiliado.
    """

    __tablename__ = "affiliate_withdrawals"

    # Tenant
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant = relationship("Tenant", back_populates="affiliate_withdrawals")

    # Usuário afiliado solicitante
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user = relationship("User", back_populates="affiliate_withdrawals")

    # Conta de destino (opcional, pode usar withdrawal_accounts)
    withdrawal_account_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("withdrawal_accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    withdrawal_account = relationship("WithdrawalAccount", back_populates="affiliate_withdrawals")

    # Valor solicitado em centavos
    amount_cents: Mapped[int] = mapped_column(Numeric(12, 0), nullable=False)

    # Status do saque
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING")
    # Valores: PENDING, PROCESSING, PAID, FAILED, CANCELLED

    # Chave de idempotência
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)

    # Resposta do provedor (webhook)
    provider_response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Data de confirmação do provedor
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<AffiliateWithdrawal(id={self.id}, user_id={self.user_id}, status={self.status}, amount={self.amount_cents})>"
