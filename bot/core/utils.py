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
from typing import Optional, Sequence, Tuple, Union
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

def format_datetime(dt: datetime, fmt: str = "%d/%m/%Y %H:%M:%S") -> str:
    """
    Formata um objeto datetime para string no padrão brasileiro.

    Args:
        dt: Objeto datetime (com timezone ou não).
        fmt: Formato desejado.

    Returns:
        str: Data/hora formatada.
    """
    if dt
