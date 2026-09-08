"""
Pacote de workers (tarefas assíncronas).

Contém as definições de tarefas que serão executadas em segundo plano
usando arq (fila baseada em Redis). Este módulo pode importar
WorkerSettings de tasks para uso direto pelo comando arq.
"""

from bot.workers.tasks import WorkerSettings

__all__ = ["WorkerSettings"]
