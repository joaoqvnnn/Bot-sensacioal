"""
Constantes e enums do sistema.

Centraliza valores fixos para status de pagamentos, pedidos, estoque,
métodos de entrega, tipos de ledger, etc. Evita strings soltas e conflitos.
"""

from enum import Enum


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class InventoryStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    SOLD = "SOLD"


class DeliveryMethod(str, Enum):
    TELEGRAM = "TELEGRAM"
    WHATSAPP = "WHATSAPP"
    EMAIL = "EMAIL"


class LedgerEntryType(str, Enum):
    DEPOSIT = "deposit"
    BONUS = "bonus"
    PURCHASE = "purchase"
    WITHDRAWAL = "withdrawal"
    GIFT = "gift"
    POINTS_CONVERSION = "points_conversion"
    REVERSAL = "reversal"
    ADJUSTMENT = "adjustment"


class GiftCardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESERVED = "RESERVED"
    REDEEMED = "REDEEMED"
    EXPIRED = "EXPIRED"


class WithdrawalStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    PAID = "PAID"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class DeliveryJobStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class SupportTicketStatus(str, Enum):
    OPEN = "OPEN"
    WAITING_USER = "WAITING_USER"
    WAITING_AGENT = "WAITING_AGENT"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class NotificationChannel(str, Enum):
    TELEGRAM = "TELEGRAM"
    WHATSAPP = "WHATSAPP"
    EMAIL = "EMAIL"


# Limites e padrões
DEFAULT_RESERVATION_MINUTES = 10
DEFAULT_GIFT_CARD_EXPIRY_DAYS = 365
DEFAULT_TOKEN_EXPIRY_HOURS = 24
DEFAULT_PAGE_SIZE = 5
MAX_PAGE_SIZE = 20
