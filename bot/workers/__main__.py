"""
Ponto de entrada do worker (arq).

Permite executar o worker com:
    python -m bot.workers

O worker processará as tarefas definidas em bot.workers.tasks.WorkerSettings.
"""

import asyncio
import logging
import sys

from arq import run_worker

from bot.core.config import settings
from bot.core.logging import setup_logging
from bot.workers.tasks import WorkerSettings


async def main() -> None:
    """Inicia o worker arq."""
    setup_logging(
        level=settings.LOG_LEVEL,
        app_name=f"{settings.APP_NAME}-worker",
        env=settings.APP_ENV,
    )
    logger = logging.getLogger(__name__)
    logger.info("Iniciando worker...")

    try:
        # run_worker é síncrono e bloqueante; usamos asyncio.to_thread para não travar
        await asyncio.to_thread(run_worker, WorkerSettings)
    except KeyboardInterrupt:
        logger.info("Worker encerrado pelo usuário.")
    except Exception as e:
        logger.exception(f"Erro fatal no worker: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
