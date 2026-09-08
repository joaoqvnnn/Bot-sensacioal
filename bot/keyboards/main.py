"""
Teclado principal da home do bot.

Contém os botões de navegação inicial exibidos após a verificação de canal.
Inclui botão para abrir o Mini App (WebApp) e os demais atalhos.
"""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from bot.core.config import settings


def get_main_keyboard() -> InlineKeyboardMarkup:
    """
    Retorna o teclado inline principal da home.

    Botões:
    - 🛍 Comprar Produtos
    - 🏪 Abrir Loja (Mini App)
    - 👤 Meu Perfil
    - 💰 Recarregar Saldo
    - 💎 Afiliados
    - 🏆 Top Compradores
    - 🎧 Atendimento
    - ℹ️ Sobre o Bot
    - 🔎 Pesquisar Serviços
    """
    # URL do Mini App: usa MINI_APP_URL se configurada, senão fallback para o Render
    mini_app_url = str(settings.MINI_APP_URL) if settings.MINI_APP_URL else "https://bot-sensacioal.onrender.com/miniapp"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🛍 COMPRAR PRODUTOS",
                    callback_data="menu:catalog",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏪 ABRIR LOJA",
                    web_app=WebAppInfo(url=mini_app_url),
                )
            ],
            [
                InlineKeyboardButton(
                    text="👤 MEU PERFIL",
                    callback_data="menu:profile",
                )
            ],
            [
                InlineKeyboardButton(
                    text="💰 RECARREGAR SALDO",
                    callback_data="menu:recharge",
                )
            ],
            [
                InlineKeyboardButton(
                    text="💎 AFILIADOS",
                    callback_data="menu:affiliates",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏆 TOP COMPRADORES",
                    callback_data="menu:rankings",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎧 ATENDIMENTO",
                    callback_data="menu:support",
                )
            ],
            [
                InlineKeyboardButton(
                    text="ℹ️ SOBRE O BOT",
                    callback_data="menu:about",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔎 PESQUISAR SERVIÇOS",
                    switch_inline_query_current_chat="",
                )
            ],
        ]
    )
