"""
Utilitários gerais do bot.

Fornece funções auxiliares para:
- Conversão e formatação de valores monetários (centavos <-> Real)
- Formatação de datas e horas
- Validação de entradas (WhatsApp, e-mail)
- Paginação de listas
- Truncamento de texto
"""

from datetime import datetime
from typing import List, Optional, Sequence, Tuple, Union
import re
from decimal import Decimal, InvalidOperation


# ----------------------------------------------------------------------
# FUNÇÕES MONETÁRIAS
# ----------------------------------------------------------------------

def cents_to_brl(cents: Union[int, Decimal]) -> str:
    """
    Converte valor em centavos para string em Real (R$ 0,00).

    Args:
        cents: Quantidade em centavos (inteiro).

    Returns:
        str: Valor formatado, ex: "R$ 8,00".
    """
    if cents is None:
        return "R$ 0,00"
    amount = Decimal(cents) / Decimal(100)
    # Formata com vírgula decimal e separador de milhar
    return f"R$ {amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def brl_to_cents(value: Union[str, float, Decimal]) -> Optional[int]:
    """
    Converte valor em Real para centavos (inteiro).

    Aceita strings como "10", "10,50", "10.50", "R$ 10,00".

    Args:
        value: Valor em Real.

    Returns:
        int: Valor em centavos, ou None se formato inválido.
    """
    if isinstance(value, (int, float)):
        # Converte direto; cuidado com float, preferir string
        return int(round(value * 100))

    if isinstance(value, Decimal):
        return int(value * 100)

    # Se for string, limpa e converte
    if isinstance(value, str):
        # Remove "R$", espaços, pontos de milhar, e troca vírgula decimal por ponto
        cleaned = value.strip().upper().replace("R$", "").replace(" ", "")
        cleaned = cleaned.replace(".", "").replace(",", ".")
        if not cleaned:
            return None
        try:
            decimal_value = Decimal(cleaned)
            return int(decimal_value * 100)
        except (InvalidOperation, ValueError):
            return None

    return None


# ----------------------------------------------------------------------
# FUNÇÕES DE DATA/HORA
# ----------------------------------------------------------------------

def format_datetime(dt: Optional[datetime], fmt: str = "%d/%m/%Y %H:%M:%S") -> str:
    """
    Formata um objeto datetime para string no padrão brasileiro.

    Args:
        dt: Objeto datetime (com timezone ou não).
        fmt: Formato desejado.

    Returns:
        str: Data/hora formatada.
    """
    if dt is None:
        return ""
    return dt.strftime(fmt)


def format_date(dt: Optional[datetime], fmt: str = "%d/%m/%Y") -> str:
    """
    Formata um objeto datetime para string de data apenas.

    Args:
        dt: Objeto datetime.
        fmt: Formato desejado.

    Returns:
        str: Data formatada.
    """
    return format_datetime(dt, fmt)


# ----------------------------------------------------------------------
# VALIDAÇÕES
# ----------------------------------------------------------------------

def is_valid_whatsapp(number: str) -> bool:
    """
    Verifica se um número de WhatsApp é válido (somente dígitos, 10 a 13 caracteres).

    Args:
        number: Número a validar.

    Returns:
        bool: True se válido.
    """
    if not number:
        return False
    digits = re.sub(r"\D", "", number)
    return 10 <= len(digits) <= 13


def is_valid_email(email: str) -> bool:
    """
    Verifica se um e-mail tem formato válido.

    Args:
        email: E-mail a validar.

    Returns:
        bool: True se válido.
    """
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return re.match(pattern, email) is not None


def is_valid_uuid(uuid_str: str) -> bool:
    """
    Verifica se uma string tem formato UUID v4.

    Args:
        uuid_str: String a verificar.

    Returns:
        bool: True se for UUID válido.
    """
    pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    return re.match(pattern, uuid_str.lower()) is not None


# ----------------------------------------------------------------------
# PAGINAÇÃO
# ----------------------------------------------------------------------

def paginate(items: Sequence, page: int = 1, per_page: int = 10) -> Tuple[List, int, bool, bool]:
    """
    Pagina uma lista de itens.

    Args:
        items: Lista ou sequência de itens.
        page: Página atual (1-indexada).
        per_page: Quantidade de itens por página.

    Returns:
        tuple: (itens_da_pagina, total_paginas, tem_anterior, tem_proxima)
    """
    total = len(items)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    end = start + per_page
    return list(items[start:end]), total_pages, page > 1, page < total_pages


# ----------------------------------------------------------------------
# TRUNCAMENTO
# ----------------------------------------------------------------------

def truncate_text(text: str, max_length: int = 100) -> str:
    """
    Trunca um texto para um comprimento máximo, adicionando reticências.

    Args:
        text: Texto original.
        max_length: Comprimento máximo.

    Returns:
        str: Texto truncado.
    """
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."
