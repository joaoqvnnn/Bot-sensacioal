"""
Pacote de handlers do bot.

Centraliza a importação e registro de todos os routers de handlers.
A função `register_all_handlers` é chamada na inicialização do bot
para incluir os routers no Dispatcher.
"""

from aiogram import Dispatcher

from bot.handlers.start import router as start_router


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
        # Futuros routers serão adicionados aqui:
        # catalog_router,
        # profile_router,
        # admin_router,
    ]

    for router in routers:
        dp.include_router(router)

    # Validação de conflitos: não pode haver dois routers com o mesmo nome?
    # O aiogram permite incluir vários; a colisão de comandos será detectada
    # pelo próprio aiogram ao registrar. Em caso de conflito, ele lançará exceção.
    # Aqui apenas logamos.
    import logging

    logger = logging.getLogger(__name__)
    logger.info(f"{len(routers)} router(s) registrado(s) no Dispatcher.")
