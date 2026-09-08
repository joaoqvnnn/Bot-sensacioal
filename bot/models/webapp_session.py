"""
Modelo de sessão do Mini App (WebApp).

Representa uma sessão autenticada de um usuário no Telegram Mini App,
com token seguro, expiração e dados de contexto.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import FullAuditMixin


class WebAppSession(FullAuditMixin):
    """
    Sessão ativa de um usuário no Mini App.
    """

    __tablename__ = "webapp_sessions"

    # Tenant
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant = relationship("Tenant", back_populates="webapp_sessions")

    # Usuário autenticado
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user = relationship("User", back_populates="webapp_sessions")

    # Token de sessão (hash armazenado, nunca token puro)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    # Dados adicionais (initData, etc.)
    session_data: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Status
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    # Valores: ACTIVE, EXPIRED, REVOKED

    # Data de expiração
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Último acesso
    last_accessed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<WebAppSession(id={self.id}, user_id={self.user_id}, status='{self.status}')>"
