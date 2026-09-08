"""
Pacote de handlers do bot.

Centraliza a importação e registro de todos os routers de handlers.
A função `register_all_handlers` é chamada na inicialização do bot
para incluir os routers no Dispatcher.
"""

import logging
from aiogram import Dispatcher

from bot.handlers.start import router as start_router
from bot.handlers.catalog import router as catalog_router
from bot.handlers.checkout import router as checkout_router
from bot.handlers.recharge import router as recharge_router
from bot.handlers.payment import router as payment_router
from bot.handlers.affiliate import router as affiliate_router
from bot.handlers.profile import router as profile_router
from bot.handlers.admin import router as admin_router
from bot.handlers.admin_messages import router as admin_messages_router
from bot.handlers.admin_stock import router as admin_stock_router
from bot.handlers.admin_users import router as admin_users_router
from bot.handlers.admin_anti_flood import router as admin_anti_flood_router
from bot.handlers.admin_notifications import router as admin_notifications_router
from bot.handlers.admin_general import router as admin_general_router
from bot.handlers.admin_editor_textos import router as admin_editor_textos_router
from bot.handlers.admin_buttons import router as admin_buttons_router
from bot.handlers.admin_placeholders import router as admin_placeholders_router
from bot.handlers.admin_admins import router as admin_admins_router
from bot.handlers.admin_bonus import router as admin_bonus_router
from bot.handlers.rankings import router as rankings_router
from bot.handlers.alerts import router as alerts_router
from bot.handlers.inline import router as inline_router
from bot.handlers.terms import router as terms_router
from bot.handlers.support import router as support_router


def register_all_handlers(dp: Dispatcher) -> None:
    """
    Registra todos os routers de handlers no Dispatcher.

    Args:
        dp: Instância do Dispatcher do aiogram.

    Raises:
        ValueError: Se houver conflito de handlers (por exemplo, comandos duplicados).
    """
    routers = [
        start_router,
        catalog_router,
        checkout_router,
        recharge_router,
        payment_router,
        affiliate_router,
        profile_router,
        admin_router,
        admin_messages_router,
        admin_stock_router,
        admin_users_router,
        admin_anti_flood_router,
        admin_notifications_router,
        admin_general_router,
        admin_editor_textos_router,
        admin_buttons_router,
        admin_placeholders_router,
        admin_admins_router,
        admin_bonus_router,
        rankings_router,
        alerts_router,
        inline_router,
        terms_router,
        support_router,
    ]

    for router in routers:
        dp.include_router(router)

    logger = logging.getLogger(__name__)
    logger.info(f"{len(routers)} router(s) registrado(s) no Dispatcher.")
