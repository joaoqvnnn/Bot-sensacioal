"""
Handlers de recarga de saldo via Pix.

Fluxo:
- Mostra saldo atual e botão para recarregar
- Usuário informa valor (FSM)
- Verifica mínimo, máximo e bônus
- Oferece opções de bônus (se aplicável)
- Gera pagamento Pix (via payment_service)
- Exibe QR Code e código copia-e-cola
"""

import logging
from typing import Optional

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.core.config import settings
from bot.core.database import get_async_session_factory
from bot.core.utils import cents_to_brl, brl_to_cents
from bot.keyboards.utils import create_button, add_back_button
from bot.services.user_service import get_tenant_for_bot, get_or_create_user
from bot.services.wallet_service import get_balance
from bot.services.payment_service import create_pix_payment

logger = logging.getLogger(__name__)

router = Router()


class RechargeStates(StatesGroup):
    WAITING_AMOUNT = State()


async def _get_tenant_and_user(message_or_callback):
    """Obtém tenant e usuário a partir de Message ou Callback."""
    bot = message_or_callback.bot
    user_id = message_or_callback.from_user.id
    async with get_async_session_factory() as session:
        tenant = await get_tenant_for_bot(session, bot.username)
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
    Retorna configurações de depósito (mínimo, máximo, bônus).
    Futuramente virão do banco de dados (tabela settings).
    Por ora, usamos valores do .env ou padrões.
    """
    # Esses valores devem ser movidos para configurações editáveis
    min_deposit_cents = int(settings.MERCADO_PAGO_MIN_DEPOSIT * 100)
    max_deposit_cents = int(settings.MERCADO_PAGO_MAX_DEPOSIT * 100)
    bonus_percent = 0  # default, virá do admin
    min_bonus_cents = 1000  # default, R$10,00
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

    async with get_async_session_factory() as session:
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
    if config["bonus_percent"] > 0:
        text += f"\n🎁 Bônus de recarga: {config['bonus_percent']}%"
    if config["min_bonus_cents"] > 0:
        text += f"\n❗️ Recarga mínima para ganhar o bônus: {cents_to_brl(config['min_bonus_cents'])}"

    await state.set_state(RechargeStates.WAITING_AMOUNT)
    try:
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[create_button("🔙 CANCELAR", "menu:recharge")]]
            ),
        )
    except Exception:
        await callback.message.answer(
            text,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[create_button("🔙 CANCELAR", "menu:recharge")]]
            ),
        )
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

    # Verifica bônus
    bonus_percent = config["bonus_percent"]
    min_bonus = config["min_bonus_cents"]
    eligible_for_bonus = bonus_percent > 0 and amount_cents >= min_bonus

    if eligible_for_bonus:
        bonus_cents = int(amount_cents * bonus_percent / 100)
        final_cents = amount_cents + bonus_cents
        text = (
            f"🎁 Eiii, eu tenho algo para você!\n"
            f"Recarregando {cents_to_brl(amount_cents)} você ganha {bonus_percent}% de bônus "
            f"(+{cents_to_brl(bonus_cents)}).\n"
            f"💰 Saldo final: {cents_to_brl(final_cents)}\n\n"
            "Confirme:"
        )
        buttons = [
            [create_button(f"💠 RECARREGAR {cents_to_brl(amount_cents)}", f"recharge:confirm:{amount_cents}")],
            [create_button("✏️ DIGITAR OUTRO VALOR", "recharge:pix")],
            [create_button("🔙 CANCELAR", "menu:recharge")],
        ]
    else:
        # Se não elegível, mas existe bônus e valor menor que mínimo
        if bonus_percent > 0 and amount_cents < min_bonus:
            missing = min_bonus - amount_cents
            text = (
                f"🎁 Eiii, eu tenho algo para você!\n"
                f"Recarregando {cents_to_brl(min_bonus)} você ganha {bonus_percent}% de bônus "
                f"(+{cents_to_brl(int(min_bonus * bonus_percent / 100))}), tem certeza que vai perder essa?\n"
                f"💡 Faltam apenas {cents_to_brl(missing)} para ganhar o bônus!"
            )
            buttons = [
                [create_button(f"💰 CONTINUAR COM {cents_to_brl(amount_cents)}", f"recharge:confirm:{amount_cents}")],
                [create_button(f"🎁 RECARREGAR {cents_to_brl(min_bonus)} E GANHAR BÔNUS", f"recharge:confirm:{min_bonus}")],
                [create_button("✏️ DIGITAR OUTRO VALOR", "recharge:pix")],
                [create_button("🔙 CANCELAR", "menu:recharge")],
            ]
        else:
            # Sem bônus
            text = (
                f"💰 Recarga de {cents_to_brl(amount_cents)}\n"
                "Confirme para gerar o Pix."
            )
            buttons = [
                [create_button(f"💠 GERAR PIX {cents_to_brl(amount_cents)}", f"recharge:confirm:{amount_cents}")],
                [create_button("✏️ DIGITAR OUTRO VALOR", "recharge:pix")],
                [create_button("🔙 CANCELAR", "menu:recharge")],
            ]

    await state.clear()
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(F.data.startswith("recharge:confirm:"))
async def confirm_recharge(callback: CallbackQuery, state: FSMContext):
    """Confirma recarga, gera pagamento Pix e mostra QR Code."""
    amount_cents = int(callback.data.split(":")[-1])

    tenant, user = await _get_tenant_and_user(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    # Gera idempotency key única
    idempotency_key = f"recharge:{user.id}:{callback.message.message_id}"

    async with get_async_session_factory() as session:
        try:
            payment = await create_pix_payment(
                session=session,
                tenant_id=tenant.id,
                user_id=user.id,
                amount_cents=amount_cents,
                bonus_cents=0,  # bônus será calculado no serviço de pagamento
                idempotency_key=idempotency_key,
            )
        except NotImplementedError:
            await callback.message.edit_text(
                "⚠️ A integração com Mercado Pago ainda não foi configurada.\n"
                "Não foi possível gerar o Pix. Contate o administrador.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[[create_button("🔙 VOLTAR", "menu:recharge")]]
                ),
            )
            await callback.answer()
            return
        except Exception as e:
            logger.exception(f"Erro ao criar pagamento: {e}")
            await callback.message.edit_text(
                "❌ Ocorreu um erro ao gerar o pagamento. Tente novamente mais tarde.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[[create_button("🔙 VOLTAR", "menu:recharge")]]
                ),
            )
            await callback.answer()
            return

    # Monta mensagem com QR Code e copia-e-cola
    text = (
        "💰 Comprar Saldo com Pix Automático:\n"
        f"⏱️ Expira em: {settings.MERCADO_PAGO_EXPIRATION_MINUTES} Minutos\n"
        f"💵 Valor: {cents_to_brl(int(payment.amount_cents))}\n"
        f"✨ ID da Recarga: {payment.id}\n"
        "📃 Atenção: Este código é válido para apenas um único pagamento.\n\n"
        "💎 Pix Copia e Cola:\n"
        f"<code>{payment.pix_code}</code>\n\n"
        "💡 Dica: Clique no código acima para copiar.\n\n"
        "📊 Dados:\n"
        f"— 💰 Saldo Atual: {cents_to_brl(0)} (atualizado após pagamento)\n"
        f"— 🎁 Bônus à receber: {cents_to_brl(0)}\n"
        f"— 💸 Saldo após o pagamento: {cents_to_brl(int(payment.amount_cents))}\n"
        "🇧🇷 Após o pagamento, seu saldo será liberado instantaneamente."
    )

    buttons = [
        [create_button("🔄 VERIFICAR PAGAMENTO", f"payment:check:{payment.id}")],
        [create_button("🔙 VOLTAR", "menu:recharge")],
    ]

    try:
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")
    await callback.answer()
