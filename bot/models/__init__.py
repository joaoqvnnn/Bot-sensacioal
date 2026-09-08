"""
Modelos de banco de dados do Larizinha Store.

Este módulo centraliza a importação dos modelos para facilitar o uso
e garantir que todos sejam registrados na metadata do SQLAlchemy.
"""

from bot.models.base import (
    Base,
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    SoftDeleteMixin,
    FullAuditMixin,
)
from bot.models.tenant import Tenant
from bot.models.user import User
from bot.models.wallet import Wallet, WalletLedger
from bot.models.category import Category
from bot.models.product import Product
from bot.models.inventory_item import InventoryItem

__all__ = [
    "Base",
    "UUIDPrimaryKeyMixin",
    "TimestampMixin",
    "SoftDeleteMixin",
    "FullAuditMixin",
    "Tenant",
    "User",
    "Wallet",
    "WalletLedger",
    "Category",
    "Product",
    "InventoryItem",
]
