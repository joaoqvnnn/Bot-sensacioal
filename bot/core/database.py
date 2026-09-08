"""
Configuração do banco de dados PostgreSQL com SQLAlchemy 2.0 async.

Este módulo cria e gerencia a engine assíncrona, a fábrica de sessões
e funções auxiliares para transações. Usa asyncpg como driver.
"""

import logging
from collections.abc import AsyncGenerator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base

from bot.core.config import settings

logger = logging.getLogger(__name__)

# Base declarativa para todos os modelos
Base = declarative_base()

# Engine assíncrona (usada no bot)
_async_engine: AsyncEngine | None = None

# Fábrica de sessões assíncronas
_async_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_async_engine() -> AsyncEngine:
    """
    Retorna a engine assíncrona, criando-a se ainda não existir.

    Returns:
        AsyncEngine: Engine assíncrona do SQLAlchemy.
    """
    global _async_engine
    if _async_engine is None:
        db_url = _build_async_database_url()
        logger.info(f"Inicializando engine assíncrona para {db_url.split('@')[-1]}")  # esconde credenciais

        _async_engine = create_async_engine(
            db_url,
            echo=settings.POSTGRES_ECHO,
            pool_size=settings.POSTGRES_POOL_SIZE,
            max_overflow=settings.POSTGRES_MAX_OVERFLOW,
            pool_pre_ping=True,   # verifica conexão antes de usar
            pool_recycle=3600,    # recicla conexões a cada 1h
            connect_args={
                "ssl": settings.POSTGRES_SSL,
                "timeout": 10,
            } if settings.POSTGRES_SSL else {
                "timeout": 10,
            },
        )
    return _async_engine


def get_async_session_factory() -> async_sessionmaker[AsyncSession]:
    """
    Retorna a fábrica de sessões assíncronas.

    Returns:
        async_sessionmaker[AsyncSession]: Fábrica de sessões.
    """
    global _async_session_factory
    if _async_session_factory is None:
        engine = get_async_engine()
        _async_session_factory = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _async_session_factory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Gerador de sessão para uso em dependências (ex.: handlers do aiogram).

    Exemplo:
        async for session in get_session():
            # usar session
    """
    factory = get_async_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def create_all_tables() -> None:
    """
    Cria todas as tabelas definidas nos models.

    AVISO: Em produção, use Alembic migrations, não este método.
    Esta função é útil apenas para testes ou desenvolvimento inicial.
    """
    engine = get_async_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Tabelas criadas (modo desenvolvimento).")


async def drop_all_tables() -> None:
    """
    Remove todas as tabelas.

    AVISO: Destrutivo! Usar somente em testes.
    """
    engine = get_async_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    logger.warning("Todas as tabelas foram removidas.")


def _build_async_database_url() -> str:
    """
    Monta a URL de conexão assíncrona para PostgreSQL.

    Formato:
        postgresql+asyncpg://user:password@host:port/dbname

    A senha é obtida de settings.POSTGRES_PASSWORD (SecretStr) e
    devidamente mascarada nos logs.
    """
    user = settings.POSTGRES_USER
    password = settings.POSTGRES_PASSWORD.get_secret_value()
    host = settings.POSTGRES_HOST
    port = settings.POSTGRES_PORT
    db = settings.POSTGRES_DB

    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db}"


async def close_async_engine() -> None:
    """
    Encerra a engine assíncrona, liberando conexões.
    """
    global _async_engine
    if _async_engine is not None:
        await _async_engine.dispose()
        _async_engine = None
        logger.info("Engine assíncrona descartada.")
