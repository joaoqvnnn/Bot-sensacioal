"""
Núcleo do bot.

Contém configurações, conexões, segurança, logging e utilitários centrais.
Este módulo não importa nada pesado para evitar efeitos colaterais na inicialização.
"""

# Não importe módulos aqui para evitar imports circulares.
# Os módulos devem ser importados explicitamente onde forem necessários.

# No entanto, para conveniência, podemos reexportar alguns itens leves:
from bot.core.config import settings, get_settings
from bot.core.utils import cents_to_brl, brl_to_cents

__all__ = [
    "settings",
    "get_settings",
    "cents_to_brl",
    "brl_to_cents",
]
