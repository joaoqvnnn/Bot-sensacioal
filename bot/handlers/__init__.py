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
from bot.handlers.recharge import router as recharge_router
from bot.handlers.payment import router as payment_router
from bot.handlers.affiliate import router as affiliate_router
from bot.handlers.profile import router as profile_router
from bot.handlers.admin import router as admin_router
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
    # Lista de routers a registrar
    routers = [
        start_router,
        catalog_router,
        recharge_router,
        payment_router,
        affiliate_router,
        profile_router,
        admin_router,
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
