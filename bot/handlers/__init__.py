"""
Pacote de handlers do bot.

Centraliza a importação e registro de todos os routers de handlers.
A função `register_all_handlers` é chamada na inicialização do bot
para incluir os routers no Dispatcher.
"""

import logging
from aiogram import Dispatcher

# Handlers de usuário
from bot.handlers.start import router as start_router
from bot.handlers.catalog import router as catalog_router
from bot.handlers.checkout import router as checkout_router
from bot.handlers.recharge import router as recharge_router
from bot.handlers.payment import router as payment_router
from bot.handlers.affiliate import router as affiliate_router
from bot.handlers.profile import router as profile_router
from bot.handlers.rankings import router as rankings_router
from bot.handlers.alerts import router as alerts_router
from bot.handlers.inline import router as inline_router
from bot.handlers.terms import router as terms_router
from bot.handlers.support import router as support_router

# Handlers administrativos (painel completo)
from bot.handlers.admin import router as admin_router
from bot.handlers.admin_general import router as admin_general_router
from bot.handlers.admin_editor_textos import router as admin_editor_textos_router
from bot.handlers.admin_buttons import router as admin_buttons_router
from bot.handlers.admin_placeholders import router as admin_placeholders_router
from bot.handlers.admin_admins import router as admin_admins_router
from bot.handlers.admin_bonus import router as admin_bonus_router
from bot.handlers.admin_broadcast import router as admin_broadcast_router
from bot.handlers.admin_scheduler import router as admin_scheduler_router
from bot.handlers.admin_categories import router as admin_categories_router
from bot.handlers.admin_products import router as admin_products_router
from bot.handlers.admin_inventory import router as admin_inventory_router
from bot.handlers.admin_reservation import router as admin_reservation_router
from bot.handlers.admin_payments import router as admin_payments_router
from bot.handlers.admin_wallet import router as admin_wallet_router
from bot.handlers.admin_affiliates import router as admin_affiliates_router
from bot.handlers.admin_withdrawals import router as admin_withdrawals_router
from bot.handlers.admin_bank_accounts import router as admin_bank_accounts_router
from bot.handlers.admin_email import router as admin_email_router
from bot.handlers.admin_whatsapp import router as admin_whatsapp_router
from bot.handlers.admin_ai import router as admin_ai_router
from bot.handlers.admin_search import router as admin_search_router
from bot.handlers.admin_rankings import router as admin_rankings_router
from bot.handlers.admin_alerts import router as admin_alerts_router
from bot.handlers.admin_security import router as admin_security_router
from bot.handlers.admin_mini_app import router as admin_mini_app_router
from bot.handlers.admin_multitenant import router as admin_multitenant_router
from bot.handlers.admin_updates import router as admin_updates_router
from bot.handlers.admin_integrity import router as admin_integrity_router


def register_all_handlers(dp: Dispatcher) -> None:
    """
    Registra todos os routers de handlers no Dispatcher.

    Args:
        dp: Instância do Dispatcher do aiogram.

    Raises:
        ValueError: Se houver conflito de handlers (por exemplo, comandos duplicados).
    """
    # Lista de routers a registrar
    routers = [
        # Usuário
        start_router,
        catalog_router,
        checkout_router,
        recharge_router,
        payment_router,
        affiliate_router,
        profile_router,
        rankings_router,
        alerts_router,
        inline_router,
        terms_router,
        support_router,

        # Admin
        admin_router,
        admin_general_router,
        admin_editor_textos_router,
        admin_buttons_router,
        admin_placeholders_router,
        admin_admins_router,
        admin_bonus_router,
        admin_broadcast_router,
        admin_scheduler_router,
        admin_categories_router,
        admin_products_router,
        admin_inventory_router,
        admin_reservation_router,
        admin_payments_router,
        admin_wallet_router,
        admin_affiliates_router,
        admin_withdrawals_router,
        admin_bank_accounts_router,
        admin_email_router,
        admin_whatsapp_router,
        admin_ai_router,
        admin_search_router,
        admin_rankings_router,
        admin_alerts_router,
        admin_security_router,
        admin_mini_app_router,
        admin_multitenant_router,
        admin_updates_router,
        admin_integrity_router,
    ]

    for router in routers:
        dp.include_router(router)

    logger = logging.getLogger(__name__)
    logger.info(f"{len(routers)} router(s) registrado(s) no Dispatcher.")
