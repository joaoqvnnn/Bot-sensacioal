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
        # Futuros routers serão adicionados aqui:
        # profile_router,
        # payment_router,
        # admin_router,
    ]

    for router in routers:
        dp.include_router(router)

    logger = logging.getLogger(__name__)
    logger.info(f"{len(routers)} router(s) registrado(s) no Dispatcher.")
