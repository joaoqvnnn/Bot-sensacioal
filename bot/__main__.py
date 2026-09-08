"""
Ponto de entrada principal do bot Larizinha Store.

Carrega configurações, logging, banco de dados, Redis, registra handlers
e inicia o polling. Nenhuma regra de negócio deve estar aqui.
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
from bot.core.logging import setup_logging
from bot.core.redis import create_redis_client, close_redis_client
from bot.handlers import register_all_handlers


async def main() -> None:
    """Inicializa e executa o bot."""
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
        storage = RedisStorage(redis=redis_client)
    else:
        storage = MemoryStorage()

    # Cria bot com parse mode HTML
    bot = Bot(
        token=settings.TELEGRAM_BOT_TOKEN.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    # Cria dispatcher
    dp = Dispatcher(storage=storage)

    # Registra todos os handlers
    register_all_handlers(dp)
    logger.info("Handlers registrados com sucesso.")

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
        await close_redis_client(redis_client)
        logger.info("Recursos liberados. Bot encerrado.")


if __name__ == "__main__":
    asyncio.run(main())
