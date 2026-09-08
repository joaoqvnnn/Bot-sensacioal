"""
Pacote de middlewares do bot.

Contém middlewares para anti-flood, manutenção e identificação de tenant.
Eles devem ser registrados no Dispatcher na inicialização.
"""

from bot.middlewares.anti_flood import AntiFloodMiddleware
from bot.middlewares.maintenance import MaintenanceMiddleware
from bot.middlewares.tenant import TenantMiddleware

__all__ = [
    "AntiFloodMiddleware",
    "MaintenanceMiddleware",
    "TenantMiddleware",
]
