"""
Utilitários para criação de teclados inline.

Fornece helpers para gerar botões InlineKeyboardButton e
organizá-los em linhas, com suporte a callbacks e URLs.
"""

from typing import List, Optional, Tuple, Union

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def create_button(
    text: str,
    callback_data: Optional[str] = None,
    url: Optional[str] = None,
) -> InlineKeyboardButton:
    """
    Cria um botão inline simples.

    Regras:
    - Se `url` for fornecida, o botão será de URL (callback ignorado).
    - Caso contrário, usa callback_data.

    Args:
        text: Texto visível do botão.
        callback_data: Dados do callback (ex: "menu:catalog").
        url: URL para botão de link.

    Returns:
        InlineKeyboardButton: Botão criado.

    Raises:
        ValueError: Se nem callback_data nem url forem fornecidos.
    """
    if url:
        return InlineKeyboardButton(text=text, url=url)
    if callback_data:
        return InlineKeyboardButton(text=text, callback_data=callback_data)
    raise ValueError("É necessário fornecer callback_data ou url.")


def create_inline_keyboard(
    buttons: List[Union[InlineKeyboardButton, Tuple[str, str]]],
    row_width: int = 2,
) -> InlineKeyboardMarkup:
    """
    Cria um teclado inline organizado em linhas de até `row_width` botões.

    Args:
        buttons: Lista de botões ou tuplas (texto, callback_data).
        row_width: Quantidade máxima de botões por linha.

    Returns:
        InlineKeyboardMarkup: Teclado construído.
    """
    inline_buttons = []
    for btn in buttons:
        if isinstance(btn, InlineKeyboardButton):
            inline_buttons.append(btn)
        elif isinstance(btn, tuple):
            text, callback_data = btn
            inline_buttons.append(create_button(text, callback_data))
        else:
            raise TypeError("Botão deve ser InlineKeyboardButton ou tupla (texto, callback).")

    # Agrupa em linhas
    rows = []
    for i in range(0, len(inline_buttons), row_width):
        rows.append(inline_buttons[i:i + row_width])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def add_back_button(
    keyboard: InlineKeyboardMarkup,
    callback_data: str = "back",
    text: str = "🔙 VOLTAR",
) -> InlineKeyboardMarkup:
    """
    Adiciona um botão de voltar ao final do teclado.

    Args:
        keyboard: Teclado atual.
        callback_data: Callback data do botão.
        text: Texto do botão.

    Returns:
        InlineKeyboardMarkup: Novo teclado com botão de voltar.
    """
    # Cria cópia das linhas existentes
    rows = [list(row) for row in keyboard.inline_keyboard]
    rows.append([create_button(text, callback_data)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def create_pagination_buttons(
    page: int,
    total_pages: int,
    callback_prefix: str = "page",
) -> List[InlineKeyboardButton]:
    """
    Cria botões de paginação (⬅️ Anterior, página, Próximo ➡️).

    Args:
        page: Página atual.
        total_pages: Total de páginas.
        callback_prefix: Prefixo dos callbacks (ex: "history").

    Returns:
        List[InlineKeyboardButton]: Lista com botões de paginação.
    """
    buttons = []
    if page > 1:
        buttons.append(create_button("⬅️", f"{callback_prefix}:{page-1}"))
    buttons.append(create_button(f"{page}/{total_pages}", callback_data="none"))
    if page < total_pages:
        buttons.append(create_button("➡️", f"{callback_prefix}:{page+1}"))
    return buttons


def create_back_button(callback_data: str = "back", text: str = "🔙 VOLTAR") -> InlineKeyboardButton:
    """
    Cria um botão de voltar individual.

    Args:
        callback_data: Dados do callback.
        text: Texto do botão.

    Returns:
        InlineKeyboardButton: Botão de voltar.
    """
    return create_button(text, callback_data)


def merge_keyboards(
    keyboard1: InlineKeyboardMarkup,
    keyboard2: InlineKeyboardMarkup,
) -> InlineKeyboardMarkup:
    """
    Combina dois teclados em um único, mantendo as linhas.

    Args:
        keyboard1: Primeiro teclado.
        keyboard2: Segundo teclado.

    Returns:
        InlineKeyboardMarkup: Teclado combinado.
    """
    rows = list(keyboard1.inline_keyboard) + list(keyboard2.inline_keyboard)
    return InlineKeyboardMarkup(inline_keyboard=rows)
