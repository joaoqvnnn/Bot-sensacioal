"""
Handlers de recarga de saldo via Pix.

Fluxo:
- Mostra saldo atual e botão para recarregar
- Usuário informa valor (FSM)
- Verifica mínimo, máximo e bônus
- Se bônus desativado, gera Pix diretamente
- Se bônus ativo, oferece opções de bônus
- Gera pagamento Pix real e exibe QR Code + Copia e Cola
"""

import logging
from typing import Optional

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.core.config import settings
from bot.core.database import get_async_session_factory
from bot.core.utils import cents_to_brl, brl_to_cents
from bot.keyboards.utils import create_button
from bot.services.user_service import get_tenant_for_bot, get_or_create_user
from bot.services.wallet_service import get_balance
from bot.services.payment_service import create_pix_payment

logger = logging.getLogger(__name__)

router = Router()


class RechargeStates(StatesGroup):
    WAITING_AMOUNT = State()


async def _get_tenant_and_user(message_or_callback):
    """Obtém tenant e usuário a partir de Message ou Callback."""
    user_id = message_or_callback.from_user.id

    factory = get_async_session_factory()
    async with factory() as session:
        tenant = await get_tenant_for_bot(session, settings.TELEGRAM_BOT_USERNAME)
        if tenant is None:
            return None, None
        user = await get_or_create_user(
            session=session,
            tenant=tenant,
            telegram_id=user_id,
            username=message_or_callback.from_user.username,
            first_name=message_or_callback.from_user.first_name,
            last_name=message_or_callback.from_user.last_name,
        )
        return tenant, user


def get_deposit_config():
    """
    Retorna configurações de depósito.
    Futuramente virão do banco de dados (tabela settings).
    """
    # Valores padrão; podem ser alterados no admin
    min_deposit_cents = int(settings.MERCADO_PAGO_MIN_DEPOSIT * 100)
    max_deposit_cents = int(settings.MERCADO_PAGO_MAX_DEPOSIT * 100)
    bonus_percent = 0       # 0 = desativado
    min_bonus_cents = 1000  # R$ 10,00
    return {
        "min_deposit_cents": min_deposit_cents,
        "max_deposit_cents": max_deposit_cents,
        "bonus_percent": bonus_percent,
        "min_bonus_cents": min_bonus_cents,
    }


@router.callback_query(F.data == "menu:recharge")
async def show_recharge_menu(callback: CallbackQuery, state: FSMContext):
    """Exibe tela de recarga com saldo e opção de Pix rápido."""
    tenant, user = await _get_tenant_and_user(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    factory = get_async_session_factory()
    async with factory() as session:
        balance_cents = await get_balance(session, tenant.id, user.id)

    text = (
        "💰 Recarregar Saldo\n\n"
        f"🆔 ID da Carteira: {user.telegram_id}\n"
        f"💰 Saldo Disponível: {cents_to_brl(balance_cents)}\n\n"
        "📍 Opte por 💠 Pix Rápido para que seu saldo seja creditado imediatamente.\n"
        "💡 Selecione uma opção para recarregar:"
    )

    buttons = [
        [create_button("💠 PIX RÁPIDO", "recharge:pix")],
        [create_button("🔙 VOLTAR", "menu:back")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "recharge:pix")
async def ask_amount(callback: CallbackQuery, state: FSMContext):
    """Pede o valor desejado para recarga."""
    config = get_deposit_config()
    min_deposit = cents_to_brl(config["min_deposit_cents"])

    text = (
        "ℹ️ Informe o valor que deseja recarregar:\n"
        f"🔻 Recarga mínima: {min_deposit}\n"
        "⚠️ Por favor, envie o valor que deseja recarregar agora.\n"
        "Ao realizar um depósito você declara ter lido e estar de acordo com nossos /termos"
    )

    await state.set_state(RechargeStates.WAITING_AMOUNT)

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "menu:recharge")]]
    )
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard)
    await callback.answer()


@router.message(RechargeStates.WAITING_AMOUNT)
async def process_amount(message: Message, state: FSMContext):
    """Processa valor informado, valida e oferece opções de bônus se necessário."""
    text_value = message.text.strip() if message.text else ""
    amount_cents = brl_to_cents(text_value)

    if amount_cents is None:
        await message.answer("❌ Valor inválido! Envie apenas números.\nExemplo: 10 ou 25.50")
        return

    tenant, user = await _get_tenant_and_user(message)
    if tenant is None:
        await message.answer("Sistema indisponível.")
        await state.clear()
        return

    config = get_deposit_config()
    min_deposit = config["min_deposit_cents"]
    max_deposit = config["max_deposit_cents"]

    if amount_cents < min_deposit:
        await message.answer(f"❌ Valor abaixo do mínimo: {cents_to_brl(min_deposit)}")
        return
    if amount_cents > max_deposit:
        await message.answer(f"❌ Valor acima do máximo: {cents_to_brl(max_deposit)}")
        return

    bonus_percent = config["bonus_percent"]
    min_bonus = config["min_bonus_cents"]

    # Se bônus desativado ou valor não atinge mínimo, vai direto para geração
    if bonus_percent == 0 or amount_cents >= min_bonus:
        await state.clear()
        await generate_pix(message, amount_cents, user, tenant)
        return

    # Se valor abaixo do mínimo para bônus, oferece opções
    missing = min_bonus - amount_cents
    bonus_value = int(min_bonus * bonus_percent / 100)

    text = (
        f"🎁 Eiii, eu tenho algo pra você!\n\n"
        f"Recarregando {cents_to_brl(min_bonus)} você ganha {bonus_percent}% de bônus "
        f"(+{cents_to_brl(bonus_value)}), tem certeza que vai perder essa?\n\n"
        f"💡 Faltam apenas {cents_to_brl(missing)} para ganhar o bônus!"
    )

    buttons = [
        [create_button(f"💰 CONTINUAR COM {cents_to_brl(amount_cents)}", f"recharge:confirm:{amount_cents}")],
        [create_button(f"🎁 RECARREGAR {cents_to_brl(min_bonus)} E GANHAR BÔNUS", f"recharge:confirm:{min_bonus}")],
        [create_button("✏️ DIGITAR OUTRO VALOR", "recharge:pix")],
        [create_button("🔙 CANCELAR", "menu:recharge")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await state.clear()
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("recharge:confirm:"))
async def confirm_recharge(callback: CallbackQuery, state: FSMContext):
    """Confirma recarga e gera Pix."""
    amount_cents = int(callback.data.split(":")[-1])

    tenant, user = await _get_tenant_and_user(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    await generate_pix(callback, amount_cents, user, tenant)


async def generate_pix(event, amount_cents: int, user, tenant):
    """Gera Pix e exibe QR Code + Copia e Cola."""
    idempotency_key = f"recharge:{user.id}:{id(event)}"

    factory = get_async_session_factory()
    async with factory() as session:
        try:
            payment = await create_pix_payment(
                session=session,
                tenant_id=tenant.id,
                user_id=user.id,
                amount_cents=amount_cents,
                bonus_cents=0,
                idempotency_key=idempotency_key,
            )
        except Exception as e:
            logger.exception(f"Erro ao criar pagamento: {e}")
            text = "❌ Erro ao gerar pagamento. Tente novamente."
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[[create_button("🔙 VOLTAR", "menu:recharge")]]
            )
            if isinstance(event, CallbackQuery):
                await event.message.edit_text(text, reply_markup=keyboard)
                await event.answer()
            else:
                await event.answer(text, reply_markup=keyboard)
            return

    # Monta mensagem com QR Code e copia-e-cola
    text = (
        "💰 Comprar Saldo com Pix Automático:\n\n"
        f"⏱️ Expira em: {settings.MERCADO_PAGO_EXPIRATION_MINUTES} Minutos\n"
        f"💵 Valor: {cents_to_brl(int(payment.amount_cents))}\n"
        f"✨ ID da Recarga: {payment.id}\n\n"
        "📃 Atenção: Este código é válido para apenas um único pagamento.\n"
        "Se você utilizá-lo mais de uma vez, o saldo adicional será perdido sem direito a reembolso.\n\n"
        "💎 Pix Copia e Cola:\n"
        f"<code>{payment.pix_code}</code>\n\n"
        "💡 Dica: Clique no código acima para copiar.\n\n"
        "📊 Dados:\n"
        f"— 💰 Saldo Atual: {cents_to_brl(0)}\n"
        f"— 🎁 Bônus à receber: {cents_to_brl(0)}\n"
        f"— 💸 Saldo após o pagamento: {cents_to_brl(int(payment.amount_cents))}\n\n"
        "🇧🇷 Após o pagamento, seu saldo será liberado instantaneamente."
    )

    buttons = [
        [InlineKeyboardButton("📋 COPIAR PIX", callback_data=f"payment:copy:{payment.id}")],
        [InlineKeyboardButton("🔄 VERIFICAR PAGAMENTO", callback_data=f"payment:check:{payment.id}")],
        [InlineKeyboardButton("🔙 VOLTAR", callback_data="menu:recharge")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    if isinstance(event, CallbackQuery):
        try:
            await event.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        except Exception:
            await event.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
        await event.answer()
    else:
        await event.answer(text, reply_markup=keyboard, parse_mode="HTML")
