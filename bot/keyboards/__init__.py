"""
Pacote de teclados do bot.

Contém helpers e teclados pré-definidos para as principais telas.
Reexporta funções utilitárias para construção de botões.
"""

from bot.keyboards.utils import (
    create_button,
    create_inline_keyboard,
    add_back_button,
    create_pagination_buttons,
    create_back_button,
    merge_keyboards,
)
from bot.keyboards.main import get_main_keyboard

__all__ = [
    "create_button",
    "create_inline_keyboard",
    "add_back_button",
    "create_pagination_buttons",
    "create_back_button",
    "merge_keyboards",
    "get_main_keyboard",
]
