"""
Handlers administrativos de Placeholders.

Seção 4 do painel: exibe os placeholders suportados e permite ao administrador
testar textos com validação. Isso garante que nenhum placeholder inexistente
seja utilizado nas mensagens editáveis.
"""

import logging
import re
from typing import Set

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.keyboards.utils import create_button

logger = logging.getLogger(__name__)

router = Router()


class PlaceholderStates(StatesGroup):
    WAITING_TEST_TEXT = State()


# Lista de placeholders permitidos (deve espelhar bot/core/constants.py ou utils)
ALLOWED_PLACEHOLDERS: Set[str] = {
    "user_id",
    "username",
    "first_name",
    "balance",
    "total_users",
    "total_sales",
    "total_revenue",
    "product_name",
    "price",
    "stock",
    "sold_count",
    "viewers",
    "duration",
    "guarantee",
    "order_id",
    "payment_id",
    "expires_at",
    "bonus",
    "pix_code",
    "affiliate_link",
    "referral_count",
    "commission_balance",
    "withdrawal_min",
    "tenant_id",
    "plan",
    "bot_version",
}


async def _edit_or_answer(callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup):
    """Edita a mensagem atual, se possível."""
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard)
    await callback.answer()


def _validate_placeholders(text: str) -> Set[str]:
    """Retorna placeholders inválidos encontrados no texto."""
    found = set(re.findall(r"\{(.*?)\}", text))
    return {p for p in found if p not in ALLOWED_PLACEHOLDERS}


@router.callback_query(F.data == "admin:placeholders")
async def show_placeholders(callback: CallbackQuery, state: FSMContext):
    """Exibe a lista de placeholders permitidos e opções de teste."""
    text = (
        "🧩 PLACEHOLDERS\n\n"
        "Estes são os placeholders permitidos nas mensagens:\n"
        + "\n".join(f"• {p}" for p in sorted(ALLOWED_PLACEHOLDERS))
        + "\n\n"
        "Você pode testar um texto para ver se contém placeholders inválidos."
    )
    buttons = [
        [create_button("🧪 Testar texto", "admin:placeholders:test")],
        [create_button("🔙 VOLTAR", "admin:main")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "admin:placeholders:test")
async def test_placeholder(callback: CallbackQuery, state: FSMContext):
    """Pede um texto para testar a validação de placeholders."""
    await state.set_state(PlaceholderStates.WAITING_TEST_TEXT)
    text = "Digite o texto que deseja testar (pode incluir placeholders como {user_id}, {balance}):"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "admin:placeholders")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(PlaceholderStates.WAITING_TEST_TEXT)
async def process_test_text(message: Message, state: FSMContext):
    """Valida o texto e informa placeholders inválidos."""
    test_text = message.text.strip() if message.text else ""
    if not test_text:
        await message.answer("Texto vazio.")
        return

    invalid = _validate_placeholders(test_text)
    if invalid:
        await message.answer(
            f"❌ Placeholders inválidos encontrados:\n"
            + "\n".join(f"• {p}" for p in invalid)
            + "\n\nUse apenas placeholders da lista permitida."
        )
    else:
        await message.answer("✅ Nenhum placeholder inválido encontrado.")

    await state.clear()
