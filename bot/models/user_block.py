"""
Modelo de bloqueio de usuário.

Representa o bloqueio de um usuário no bot, seja temporário ou permanente,
com motivo e registro de quem aplicou o bloqueio.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import FullAuditMixin


class UserBlock(FullAuditMixin):
    """
    Bloqueio aplicado a um usuário.
    """

    __tablename__ = "user_blocks"

    # Tenant
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant = relationship("Tenant", back_populates="user_blocks")

    # Usuário bloqueado
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user = relationship("User", back_populates="user_blocks")

    # Tipo de bloqueio
    block_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # Valores: TEMPORARY, PERMANENT

    # Motivo
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    # Data de expiração (para bloqueio temporário)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Administrador que aplicou
    blocked_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    blocked_by_user = relationship("User", foreign_keys=[blocked_by_user_id])

    # Status
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    def __repr__(self) -> str:
        return f"<UserBlock(id={self.id}, user_id={self.user_id}, type='{self.block_type}')>"
