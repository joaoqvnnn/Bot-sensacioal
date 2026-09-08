"""
Cliente Redis assíncrono para o bot.

Este módulo fornece uma função para criar e validar a conexão com o Redis,
utilizando a biblioteca redis.asyncio. A instância deve ser criada durante
a inicialização do bot (em bot/__main__.py) e injetada onde necessário.

Nenhuma conexão é aberta no momento da importação deste módulo.
"""

import logging
from typing import Optional

import redis.asyncio as aioredis

from bot.core.config import Settings

logger = logging.getLogger(__name__)


async def create_redis_client(settings: Settings) -> aioredis.Redis:
    """
    Cria e valida um cliente Redis assíncrono.

    Args:
        settings: Instância de Settings contendo REDIS_HOST, REDIS_PORT,
                  REDIS_PASSWORD e REDIS_DB.

    Returns:
        aioredis.Redis: Cliente Redis pronto para uso.

    Raises:
        ConnectionError: Se o Redis não estiver acessível ou a senha for inválida.
        ValueError: Se a senha do Redis estiver vazia (em produção).
    """
    redis_password = settings.REDIS_PASSWORD.get_secret_value()

    if not redis_password:
        if settings.APP_ENV == "production":
            raise ValueError("REDIS_PASSWORD não pode ser vazia em produção.")
        logger.warning("REDIS_PASSWORD vazia. Conectando sem senha (apenas desenvolvimento).")
        redis_password = None

    logger.info(f"Conectando ao Redis em {settings.REDIS_HOST}:{settings.REDIS_PORT} ...")

    client = aioredis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        db=settings.REDIS_DB,
        password=redis_password,
        decode_responses=True,          # retorna strings, não bytes
        socket_timeout=5.0,             # timeout de socket
        socket_connect_timeout=5.0,     # timeout de conexão
        retry_on_timeout=False,         # evita retries automáticos que mascaram problemas
        health_check_interval=30,       # verificação periódica da conexão
    )

    try:
        # Testa a conexão com um PING
        pong = await client.ping()
        if not pong:
            raise ConnectionError("Resposta inesperada do Redis ao PING.")
        logger.info("Conexão com Redis estabelecida e validada.")
    except Exception as e:
        logger.exception(f"Falha ao conectar no Redis: {e}")
        await client.aclose()
        raise ConnectionError(f"Não foi possível conectar ao Redis: {e}") from e

    return client


async def close_redis_client(client: Optional[aioredis.Redis]) -> None:
    """
    Fecha a conexão com o Redis de forma segura.

    Args:
        client: Cliente Redis a ser fechado. Pode ser None.
    """
    if client is not None:
        try:
            await client.aclose()
            logger.info("Conexão Redis fechada.")
        except Exception as e:
            logger.warning(f"Erro ao fechar Redis: {e}")
