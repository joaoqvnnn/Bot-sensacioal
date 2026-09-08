"""
Modelos de saque e contas de saque.

Representam as contas bancárias/Pix cadastradas pelos usuários e as
solicitações de saque, com controle de status e idempotência.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import FullAuditMixin


class WithdrawalAccount(FullAuditMixin):
    """
    Conta de saque cadastrada por um usuário (chave Pix ou dados bancários).
    """

    __tablename__ = "withdrawal_accounts"

    # Tenant
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant = relationship("Tenant", back_populates="withdrawal_accounts")

    # Usuário dono da conta
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user = relationship("User", back_populates="withdrawal_accounts")

    # Tipo de conta (PIX, BANK)
    account_type: Mapped[str] = mapped_column(String(20), nullable=False)

    # Dados da conta (criptografados em produção)
    # Para Pix: chave; para Bank: banco, agência, conta, tipo, etc.
    account_data_encrypted: Mapped[str] = mapped_column(Text, nullable=False)

    # Nome do titular
    holder_name: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)

    # Se é a conta principal
    is_default: Mapped[bool] = mapped_column(default=False, nullable=False)

    def __repr__(self) -> str:
        return f"<WithdrawalAccount(id={self.id}, user_id={self.user_id}, type='{self.account_type}')>"


class Withdrawal(FullAuditMixin):
    """
    Solicitação de saque feita por um usuário.
    """

    __tablename__ = "withdrawals"

    # Tenant
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant = relationship("Tenant", back_populates="withdrawals")

    # Usuário solicitante
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user = relationship("User", back_populates="withdrawals")

    # Conta de destino
    withdrawal_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("withdrawal_accounts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    withdrawal_account = relationship("WithdrawalAccount", back_populates="withdrawals")

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
        return f"<Withdrawal(id={self.id}, user_id={self.user_id}, status={self.status}, amount={self.amount_cents})>"
