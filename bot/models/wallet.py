"""
Modelos de carteira e livro-razão financeiro.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from bot.models.base import Base, FullAuditMixin


class Wallet(Base, FullAuditMixin):
    """
    Carteira de saldo do usuário. O saldo é sempre representado em centavos (inteiro)
    para evitar problemas com ponto flutuante.
    """

    __tablename__ = "wallets"
    __table_args__ = (
        CheckConstraint("balance_cents >= 0", name="ck_wallets_balance_non_negative"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    balance_cents: Mapped[int] = mapped_column(Numeric(12, 0), default=0, nullable=False)

    def __repr__(self) -> str:
        return f"<Wallet(user_id={self.user_id}, balance_cents={self.balance_cents})>"


class WalletLedger(Base, FullAuditMixin):
    """
    Registro imutável de cada movimentação financeira na carteira.
    Cada entrada deve ter um tipo, valor em centavos e saldo resultante.
    """

    __tablename__ = "wallet_ledger"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    wallet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("wallets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    entry_type: Mapped[str] = mapped_column(String(50), nullable=False)
    amount_cents: Mapped[int] = mapped_column(Numeric(12, 0), nullable=False)
    balance_after_cents: Mapped[int] = mapped_column(Numeric(12, 0), nullable=False)

    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reference_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)

    def __repr__(self) -> str:
        return f"<WalletLedger(wallet_id={self.wallet_id}, type='{self.entry_type}', amount={self.amount_cents})>"
