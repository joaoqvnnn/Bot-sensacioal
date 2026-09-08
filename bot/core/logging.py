"""
Configuração de logging estruturado para o bot.

Utiliza structlog integrado ao logging padrão, gerando saída em JSON
para facilitar coleta e análise em ambientes de produção.
"""

import logging
import sys

import structlog


def setup_logging(
    level: str = "INFO",
    app_name: str = "LarizinhaStore",
    env: str = "development",
) -> None:
    """
    Configura o logging estruturado.

    Args:
        level: Nível de log (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        app_name: Nome da aplicação (usado em metadados).
        env: Ambiente (development, production).
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Processadores comuns para logs padrão
    pre_chain = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    # Handler de console (stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)

    # Formatter que usa JSON
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
        foreign_pre_chain=pre_chain,
    )
    console_handler.setFormatter(formatter)

    # Configura o logger raiz
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.addHandler(console_handler)

    # Remove handlers antigos para evitar duplicação (caso setup_logging seja chamado novamente)
    for handler in root_logger.handlers[:]:
        if handler is not console_handler and isinstance(handler, logging.StreamHandler):
            root_logger.removeHandler(handler)

    # Configura o structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Registra que o logging foi configurado
    logger = structlog.get_logger("setup")
    logger.info("Logging configurado", app_name=app_name, env=env)
