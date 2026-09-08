"""
Modelo de pontos de afiliados.

Representa os pontos acumulados por um usuário no programa de afiliados.
"""

import uuid
from typing import Optional

from sqlalchemy import Integer, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import FullAuditMixin


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
