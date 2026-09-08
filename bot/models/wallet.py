"""
Modelos de carteira e livro-razão financeiro.

A Wallet armazena o saldo atual do usuário.
O WalletLedger registra cada movimentação (crédito/débito) de forma imutável.
O saldo deve ser sempre calculado a partir do ledger para evitar inconsistências.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import FullAuditMixin


class Wallet(FullAuditMixin):
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

    # Relacionamentos
    tenant = relationship("Tenant", back_populates="wallets")
    user = relationship("User", back_populates="wallet")

    ledger_entries = relationship("WalletLedger", back_populates="wallet", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Wallet(user_id={self.user_id}, balance_cents={self.balance_cents})>"


class WalletLedger(FullAuditMixin):
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

    entry_type: Mapped[str] = mapped_column(String(50), nullable=False)  # credit, debit, adjustment, etc.
    amount_cents: Mapped[int] = mapped_column(Numeric(12, 0), nullable=False)
    balance_after_cents: Mapped[int] = mapped_column(Numeric(12, 0), nullable=False)

    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reference_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Relacionamentos
    tenant = relationship("Tenant", back_populates="wallet_ledger_entries")
    wallet = relationship("Wallet", back_populates="ledger_entries")
    user = relationship("User", back_populates="ledger_entries")

    def __repr__(self) -> str:
        return f"<WalletLedger(wallet_id={self.wallet_id}, type='{self.entry_type}', amount={self.amount_cents})>"
