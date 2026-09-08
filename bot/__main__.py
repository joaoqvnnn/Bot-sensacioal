"""
Ponto de entrada principal do bot Larizinha Store.

Este módulo carrega as configurações, instancia o Bot do aiogram,
o Dispatcher, aplica middlewares globais e inicia o polling.

Nenhuma regra de negócio deve estar aqui. Apenas inicialização.
"""

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage

from bot.core.config import settings
from bot.core.redis import create_redis_client
from bot.core.logging import setup_logging


async def main() -> None:
    """Função principal de inicialização e execução do bot."""
    # Configura logging estruturado
    setup_logging(
        level=settings.LOG_LEVEL,
        app_name=settings.APP_NAME,
        env=settings.APP_ENV,
    )
    logger = logging.getLogger(__name__)

    logger.info("Iniciando Larizinha Store bot...")
    logger.info(f"Ambiente: {settings.APP_ENV}")

    # Cria cliente Redis para FSM e rate limit
    redis_client = await create_redis_client(settings)

    # Configura storage do FSM
    if settings.APP_ENV == "production":
        # Em produção usa Redis para manter estado entre restarts
        storage = RedisStorage(redis=redis_client)
    else:
        # Em desenvolvimento pode usar memória (mais simples)
        storage = MemoryStorage()

    # Cria bot com parse mode HTML e token seguro
    bot = Bot(
        token=settings.TELEGRAM_BOT_TOKEN.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    # Cria dispatcher
    dp = Dispatcher(storage=storage)

    # Importa e registra handlers
    # Os handlers serão importados aqui futuramente
    # from bot.handlers import register_all_handlers
    # register_all_handlers(dp)
    logger.warning("Nenhum handler registrado ainda.")

    # Inicia polling
    try:
        logger.info("Iniciando polling...")
        await dp.start_polling(bot)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot encerrado pelo usuário.")
    except Exception as e:
        logger.exception(f"Erro fatal durante execução: {e}")
        sys.exit(1)
    finally:
        await bot.session.close()
        await redis_client.aclose()
        logger.info("Recursos liberados. Bot encerrado.")


if __name__ == "__main__":
    asyncio.run(main())
