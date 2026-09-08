"""
Teclado principal da home do bot.

Contém os botões de navegação inicial exibidos após a verificação de canal.
Futuramente esses botões serão carregados do banco de dados (tabela keyboard_layouts),
mas por enquanto mantemos uma versão estática alinhada à especificação.
"""

from aiogram.types import InlineKeyboardMarkup

from bot.keyboards.utils import create_button, create_inline_keyboard


def get_main_keyboard() -> InlineKeyboardMarkup:
    """
    Retorna o teclado inline principal da home.

    Botões (ordem e layout conforme especificação):
    - 🛍 COMPRAR PRODUTOS
    - 🏪 ABRIR LOJA
    - 👤 MEU PERFIL
    - 💰 RECARREGAR SALDO
    - 💎 AFILIADOS
    - 🏆 TOP COMPRADORES
    - 🎧 ATENDIMENTO
    - ℹ️ SOBRE O BOT
    - 🔎 PESQUISAR SERVIÇOS

    Returns:
        InlineKeyboardMarkup: Teclado da home.
    """
    buttons = [
        ("🛍 COMPRAR PRODUTOS", "menu:catalog"),
        ("🏪 ABRIR LOJA", "menu:store"),
        ("👤 MEU PERFIL", "menu:profile"),
        ("💰 RECARREGAR SALDO", "menu:recharge"),
        ("💎 AFILIADOS", "menu:affiliates"),
        ("🏆 TOP COMPRADORES", "menu:rankings"),
        ("🎧 ATENDIMENTO", "menu:support"),
        ("ℹ️ SOBRE O BOT", "menu:about"),
        ("🔎 PESQUISAR SERVIÇOS", "menu:search"),
    ]

    # Organiza em linhas de 2 botões (pode ser alterado quando vier do banco)
    return create_inline_keyboard(buttons, row_width=2)
