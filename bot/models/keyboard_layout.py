"""
Modelo de layout de teclado.

Representa um layout de botões inline configurável pelo administrador,
armazenando a estrutura dos botões em JSON e o número de botões por linha.
"""

import uuid
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Integer, String, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import FullAuditMixin


class KeyboardLayout(FullAuditMixin):
    """
    Definição de botões e layout de teclado inline.
    """

    __tablename__ = "keyboard_layouts"

    # Tenant
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant = relationship("Tenant", back_populates="keyboard_layouts")

    # Código do teclado (ex: "main_menu", "profile")
    code: Mapped[str] = mapped_column(String(100), nullable=False)

    # Dados dos botões em JSON estruturado
    buttons_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Layout: row_width padrão
    row_width: Mapped[int] = mapped_column(Integer, default=2, nullable=False)

    # Status ativo/inativo
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    def __repr__(self) -> str:
        return f"<KeyboardLayout(code='{self.code}', tenant_id={self.tenant_id})>"
