"""
Modelos de verificação de e-mail e WhatsApp.

Representam códigos de verificação de uso único, com expiração e limite
de tentativas, para confirmar e-mail e número de WhatsApp do usuário.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import FullAuditMixin


class EmailVerification(FullAuditMixin):
    """
    Código de verificação de e-mail.
    """

    __tablename__ = "email_verifications"

    # Tenant
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant = relationship("Tenant", back_populates="email_verifications")

    # Usuário
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user = relationship("User", back_populates="email_verifications")

    # E-mail a ser verificado
    email: Mapped[str] = mapped_column(String(255), nullable=False)

    # Código (hash armazenado, nunca o código puro)
    code_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    # Tentativas
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)

    # Status
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    # Valores: PENDING, VERIFIED, EXPIRED, CANCELLED

    # Data de expiração
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:
        return f"<EmailVerification(id={self.id}, email='{self.email}', status='{self.status}')>"


class WhatsAppVerification(FullAuditMixin):
    """
    Código de verificação de número de WhatsApp.
    """

    __tablename__ = "whatsapp_verifications"

    # Tenant
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant = relationship("Tenant", back_populates="whatsapp_verifications")

    # Usuário
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user = relationship("User", back_populates="whatsapp_verifications")

    # Número de WhatsApp
    whatsapp_number: Mapped[str] = mapped_column(String(20), nullable=False)

    # Código (hash armazenado)
    code_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    # Tentativas
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)

    # Status
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    # Valores: PENDING, VERIFIED, EXPIRED, CANCELLED

    # Data de expiração
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:
        return f"<WhatsAppVerification(id={self.id}, whatsapp='{self.whatsapp_number}', status='{self.status}')>"
