"""
Modelo de Pagamento.

Representa uma cobrança Pix gerada para recarga de saldo ou compra.
Todos os valores são armazenados em centavos (inteiro).
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import FullAuditMixin


class Payment(FullAuditMixin):
    """
    Entidade de pagamento Pix.
    """

    __tablename__ = "payments"

    # Relacionamento com Tenant
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant = relationship("Tenant", back_populates="payments")

    # Relacionamento com Usuário
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user = relationship("User", back_populates="payments")

    # ID externo da cobrança no provedor (ex: Mercado Pago)
    external_payment_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)

    # Status do pagamento
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING")
    # Valores possíveis: PENDING, PAID, EXPIRED, FAILED, CANCELLED

    # Valor original da cobrança (em centavos)
    amount_cents: Mapped[int] = mapped_column(Numeric(12, 0), nullable=False)

    # Valor do bônus concedido (em centavos), se houver
    bonus_cents: Mapped[int] = mapped_column(Numeric(12, 0), nullable=False, default=0)

    # Chave de idempotência para evitar processamento duplicado
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)

    # URL do QR Code e código copia-e-cola (Pix)
    qr_code_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pix_code: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Data de expiração da cobrança
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Data de confirmação do pagamento
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Dados do provedor (webhook)
    provider_response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<Payment(id={self.id}, user_id={self.user_id}, status={self.status}, amount={self.amount_cents})>"
