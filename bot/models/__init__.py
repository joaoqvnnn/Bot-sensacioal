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
from bot.models.user import User
from bot.models.tenant import Tenant
from bot.models.wallet import Wallet, WalletLedger
from bot.models.category import Category
from bot.models.product import Product
from bot.models.inventory_item import InventoryItem
from bot.models.order import Order, OrderItem
from bot.models.payment import Payment
from bot.models.referral import Referral, AffiliateCommission, AffiliatePoints
from bot.models.gift_card import GiftCard, GiftCardRedemption
from bot.models.delivery import DeliveryJob, DeliveryAttempt
from bot.models.alert import AlertSubscription
from bot.models.broadcast import Broadcast
from bot.models.scheduled_notification import ScheduledNotification
from bot.models.support import SupportTicket, SupportMessage
from bot.models.audit_log import AuditLog, AntiFloodEvent
from bot.models.settings import Settings, MessageTemplate, KeyboardLayout, MediaAsset
from bot.models.user_block import UserBlock
from bot.models.admin_user import AdminUser
from bot.models.withdrawal import Withdrawal, WithdrawalAccount
from bot.models.verification import EmailVerification, WhatsAppVerification
from bot.models.product_access_token import ProductAccessToken
from bot.models.webapp_session import WebAppSession
from bot.models.whatsapp_message import WhatsAppMessage

__all__ = [
    "Base",
    "UUIDPrimaryKeyMixin",
    "TimestampMixin",
    "SoftDeleteMixin",
    "FullAuditMixin",
    "User",
    "Tenant",
    "Wallet",
    "WalletLedger",
    "Category",
    "Product",
    "InventoryItem",
    "Order",
    "OrderItem",
    "Payment",
    "Referral",
    "AffiliateCommission",
    "AffiliatePoints",
    "GiftCard",
    "GiftCardRedemption",
    "DeliveryJob",
    "DeliveryAttempt",
    "AlertSubscription",
    "Broadcast",
    "ScheduledNotification",
    "SupportTicket",
    "SupportMessage",
    "AuditLog",
    "AntiFloodEvent",
    "Settings",
    "MessageTemplate",
    "KeyboardLayout",
    "MediaAsset",
    "UserBlock",
    "AdminUser",
    "Withdrawal",
    "WithdrawalAccount",
    "EmailVerification",
    "WhatsAppVerification",
    "ProductAccessToken",
    "WebAppSession",
    "WhatsAppMessage",
]
