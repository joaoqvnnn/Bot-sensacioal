"""
Ambiente de execução do Alembic.

Este script configura o Alembic para usar a engine assíncrona do SQLAlchemy,
carrega os modelos (para autogenerate) e fornece o contexto para as migrations.
"""

import asyncio
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Adiciona a raiz do projeto ao sys.path para importar os módulos do bot
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Importa as configurações do projeto
from bot.core.config import settings
from bot.models import Base  # noqa: F401  (garante que os modelos sejam registrados)

# Configuração de logging do Alembic (lê o arquivo alembic.ini)
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Define a URL do banco a partir das settings
config.set_main_option(
    "sqlalchemy.url",
    f"postgresql+asyncpg://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD.get_secret_value()}@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
)

# Metadados dos modelos
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    Executa migrations em modo offline (gera SQL, sem conexão).
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """
    Executa migrations com uma conexão ativa.
    """
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """
    Executa migrations usando engine assíncrona.
    """
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """
    Executa migrations em modo online (com conexão real).
    """
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
