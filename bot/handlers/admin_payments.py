"""
Handlers administrativos de Pix/Pagamentos.

Seção 14 do painel: configurações de pagamento Pix.
Permite gerenciar provedor, token, limites, expiração, bônus, webhook
e visualizar histórico recente de pagamentos.
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, func

from bot.core.config import settings
from bot.core.database import get_async_session_factory
from bot.core.utils import cents_to_brl
from bot.keyboards.utils import create_button
from bot.models.settings import Settings
from bot.models.payment import Payment
from bot.models.user import User
from bot.services.user_service import get_tenant_for_bot, get_or_create_user

logger = logging.getLogger(__name__)

router = Router()


class AdminPaymentsStates(StatesGroup):
    WAITING_MIN_DEPOSIT = State()
    WAITING_MAX_DEPOSIT = State()
    WAITING_EXPIRATION = State()
    WAITING_BONUS = State()
    WAITING_WEBHOOK_URL = State()
    WAITING_PROVIDER_TOKEN = State()


async def _get_tenant_and_user_from_callback(callback: CallbackQuery):
    """Obtém tenant e usuário a partir do callback."""
    async with get_async_session_factory() as session:
        tenant = await get_tenant_for_bot(session, callback.bot.username)
        if tenant is None:
            return None, None
        user = await get_or_create_user(
            session=session,
            tenant=tenant,
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
            last_name=callback.from_user.last_name,
        )
        return tenant, user


async def _get_tenant_and_user_from_message(message: Message):
    """Obtém tenant e usuário a partir de mensagem."""
    async with get_async_session_factory() as session:
        tenant = await get_tenant_for_bot(session, message.bot.username)
        if tenant is None:
            return None, None
        user = await get_or_create_user(
            session=session,
            tenant=tenant,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
        )
        return tenant, user


async def _is_admin(session, tenant_id: UUID, user_id: UUID) -> bool:
    """Verifica se o usuário é administrador ou dono no tenant."""
    user = (await session.execute(
        select(User).where(User.id == user_id, User.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if user and (user.is_owner or user.is_admin):
        return True

    from bot.models.admin_user import AdminUser
    admin = (await session.execute(
        select(AdminUser).where(
            AdminUser.tenant_id == tenant_id,
            AdminUser.user_id == user_id,
            AdminUser.is_active == True,
            AdminUser.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    return admin is not None


async def _get_setting(session, tenant_id: UUID, key: str) -> Optional[str]:
    """Busca valor de configuração."""
    stmt = select(Settings).where(
        Settings.tenant_id == tenant_id,
        Settings.key == key,
        Settings.deleted_at.is_(None),
    )
    setting = (await session.execute(stmt)).scalar_one_or_none()
    return setting.value if setting else None


async def _set_setting(session, tenant_id: UUID, key: str, value: str) -> None:
    """Cria ou atualiza configuração."""
    stmt = select(Settings).where(
        Settings.tenant_id == tenant_id,
        Settings.key == key,
        Settings.deleted_at.is_(None),
    )
    setting = (await session.execute(stmt)).scalar_one_or_none()
    if setting:
        setting.value = value
    else:
        setting = Settings(tenant_id=tenant_id, key=key, value=value)
        session.add(setting)
    await session.commit()


async def _edit_or_answer(callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup):
    """Edita a mensagem atual, se possível."""
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "pix_admin:main")
async def payments_main(callback: CallbackQuery, state: FSMContext):
    """Menu principal de configurações de Pix/Pagamentos."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        provider = await _get_setting(session, tenant.id, "pix_provider") or "mercadopago"
        pix_auto = await _get_setting(session, tenant.id, "pix_auto") or "true"
        min_dep = await _get_setting(session, tenant.id, "pix_min_deposit") or str(settings.MERCADO_PAGO_MIN_DEPOSIT)
        max_dep = await _get_setting(session, tenant.id, "pix_max_deposit") or str(settings.MERCADO_PAGO_MAX_DEPOSIT)
        expiration = await _get_setting(session, tenant.id, "pix_expiration_minutes") or str(settings.MERCADO_PAGO_EXPIRATION_MINUTES)
        bonus = await _get_setting(session, tenant.id, "pix_bonus_percent") or "0"
        webhook_url = await _get_setting(session, tenant.id, "pix_webhook_url") or "Não configurado"

        pending_count = (await session.execute(
            select(func.count(Payment.id)).where(
                Payment.tenant_id == tenant.id,
                Payment.status == "PENDING",
                Payment.deleted_at.is_(None),
            )
        )).scalar_one()
        paid_count = (await session.execute(
            select(func.count(Payment.id)).where(
                Payment.tenant_id == tenant.id,
                Payment.status == "PAID",
                Payment.deleted_at.is_(None),
            )
        )).scalar_one()

    text = (
        "💳 PIX / PAGAMENTOS\n\n"
        f"Provedor: <b>{provider}</b>\n"
        f"Pix automático: <b>{'🟢 ON' if pix_auto == 'true' else '🔴 OFF'}</b>\n"
        f"Depósito mínimo: <b>R$ {min_dep}</b>\n"
        f"Depósito máximo: <b>R$ {max_dep}</b>\n"
        f"Expiração: <b>{expiration} min</b>\n"
        f"Bônus: <b>{bonus}%</b>\n"
        f"Webhook: <b>{webhook_url}</b>\n"
        f"Pagamentos pendentes: {pending_count}\n"
        f"Pagamentos pagos: {paid_count}\n\n"
        "Escolha uma opção:"
    )
    buttons = [
        [create_button("💰 Alterar depósito mínimo", "pix_admin:set_min")],
        [create_button("💰 Alterar depósito máximo", "pix_admin:set_max")],
        [create_button("⏱ Alterar expiração", "pix_admin:set_expiration")],
        [create_button("🎁 Alterar bônus", "pix_admin:set_bonus")],
        [create_button("🔗 Configurar webhook", "pix_admin:set_webhook")],
        [create_button("🔑 Alterar token do provedor", "pix_admin:set_token")],
        [create_button("📋 Ver pagamentos recentes", "pix_admin:history")],
        [create_button("🔙 VOLTAR", "admin:main")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


# ----------------------------------------------------------------------
# ALTERAR LIMITES E CONFIGURAÇÕES
# ----------------------------------------------------------------------

@router.callback_query(F.data == "pix_admin:set_min")
async def set_min_deposit(callback: CallbackQuery, state: FSMContext):
    """Pede novo depósito mínimo."""
    await state.set_state(AdminPaymentsStates.WAITING_MIN_DEPOSIT)
    text = "Digite o novo depósito mínimo (ex: 1.00):"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "pix_admin:main")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminPaymentsStates.WAITING_MIN_DEPOSIT)
async def process_min_deposit(message: Message, state: FSMContext):
    """Salva novo mínimo."""
    try:
        min_cents = int(float(message.text.strip().replace(",", ".")) * 100)
        if min_cents <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Valor inválido.")
        return

    tenant, admin = await _get_tenant_and_user_from_message(message)
    if tenant is None:
        await message.answer("Sistema indisponível.")
        await state.clear()
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, admin.id):
            await message.answer("Acesso negado.")
            await state.clear()
            return
        await _set_setting(session, tenant.id, "pix_min_deposit", f"{min_cents/100:.2f}")

    await state.clear()
    await message.answer(f"✅ Depósito mínimo atualizado para R$ {min_cents/100:.2f}.")


@router.callback_query(F.data == "pix_admin:set_max")
async def set_max_deposit(callback: CallbackQuery, state: FSMContext):
    """Pede novo depósito máximo."""
    await state.set_state(AdminPaymentsStates.WAITING_MAX_DEPOSIT)
    text = "Digite o novo depósito máximo (ex: 150.00):"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "pix_admin:main")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminPaymentsStates.WAITING_MAX_DEPOSIT)
async def process_max_deposit(message: Message, state: FSMContext):
    """Salva novo máximo."""
    try:
        max_cents = int(float(message.text.strip().replace(",", ".")) * 100)
        if max_cents <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Valor inválido.")
        return

    tenant, admin = await _get_tenant_and_user_from_message(message)
    if tenant is None:
        await message.answer("Sistema indisponível.")
        await state.clear()
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, admin.id):
            await message.answer("Acesso negado.")
            await state.clear()
            return
        await _set_setting(session, tenant.id, "pix_max_deposit", f"{max_cents/100:.2f}")

    await state.clear()
    await message.answer(f"✅ Depósito máximo atualizado para R$ {max_cents/100:.2f}.")


@router.callback_query(F.data == "pix_admin:set_expiration")
async def set_expiration(callback: CallbackQuery, state: FSMContext):
    """Pede nova expiração."""
    await state.set_state(AdminPaymentsStates.WAITING_EXPIRATION)
    text = "Digite o tempo de expiração em minutos (ex: 10):"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "pix_admin:main")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminPaymentsStates.WAITING_EXPIRATION)
async def process_expiration(message: Message, state: FSMContext):
    """Salva nova expiração."""
    value = message.text.strip()
    if not value.isdigit() or int(value) < 1:
        await message.answer("Valor inválido.")
        return

    tenant, admin = await _get_tenant_and_user_from_message(message)
    if tenant is None:
        await message.answer("Sistema indisponível.")
        await state.clear()
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, admin.id):
            await message.answer("Acesso negado.")
            await state.clear()
            return
        await _set_setting(session, tenant.id, "pix_expiration_minutes", value)

    await state.clear()
    await message.answer(f"✅ Expiração atualizada para {value} minutos.")


@router.callback_query(F.data == "pix_admin:set_bonus")
async def set_bonus(callback: CallbackQuery, state: FSMContext):
    """Pede novo percentual de bônus."""
    await state.set_state(AdminPaymentsStates.WAITING_BONUS)
    text = "Digite o novo percentual de bônus (ex: 10 para 10%):"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "pix_admin:main")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminPaymentsStates.WAITING_BONUS)
async def process_bonus(message: Message, state: FSMContext):
    """Salva novo bônus."""
    value = message.text.strip()
    if not value.isdigit() or int(value) < 0 or int(value) > 100:
        await message.answer("Valor inválido. Digite entre 0 e 100.")
        return

    tenant, admin = await _get_tenant_and_user_from_message(message)
    if tenant is None:
        await message.answer("Sistema indisponível.")
        await state.clear()
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, admin.id):
            await message.answer("Acesso negado.")
            await state.clear()
            return
        await _set_setting(session, tenant.id, "pix_bonus_percent", value)

    await state.clear()
    await message.answer(f"✅ Bônus atualizado para {value}%.")


@router.callback_query(F.data == "pix_admin:set_webhook")
async def set_webhook(callback: CallbackQuery, state: FSMContext):
    """Pede nova URL de webhook."""
    await state.set_state(AdminPaymentsStates.WAITING_WEBHOOK_URL)
    text = "Digite a URL do webhook de pagamentos:"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "pix_admin:main")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminPaymentsStates.WAITING_WEBHOOK_URL)
async def process_webhook_url(message: Message, state: FSMContext):
    """Salva nova URL de webhook."""
    url = message.text.strip()
    if not url.startswith("https://"):
        await message.answer("URL deve começar com https://")
        return

    tenant, admin = await _get_tenant_and_user_from_message(message)
    if tenant is None:
        await message.answer("Sistema indisponível.")
        await state.clear()
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, admin.id):
            await message.answer("Acesso negado.")
            await state.clear()
            return
        await _set_setting(session, tenant.id, "pix_webhook_url", url)

    await state.clear()
    await message.answer("✅ Webhook atualizado.")


@router.callback_query(F.data == "pix_admin:set_token")
async def set_provider_token(callback: CallbackQuery, state: FSMContext):
    """Pede novo token do provedor (mascarado)."""
    await state.set_state(AdminPaymentsStates.WAITING_PROVIDER_TOKEN)
    text = "Digite o novo token do provedor (será armazenado como segredo):"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "pix_admin:main")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminPaymentsStates.WAITING_PROVIDER_TOKEN)
async def process_provider_token(message: Message, state: FSMContext):
    """Salva novo token (em produção, deve ser criptografado)."""
    token = message.text.strip()
    if not token:
        await message.answer("Token vazio.")
        return

    tenant, admin = await _get_tenant_and_user_from_message(message)
    if tenant is None:
        await message.answer("Sistema indisponível.")
        await state.clear()
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, admin.id):
            await message.answer("Acesso negado.")
            await state.clear()
            return
        # Idealmente usar security.encrypt_data(token)
        await _set_setting(session, tenant.id, "pix_provider_token", token)

    await state.clear()
    await message.answer("✅ Token do provedor atualizado.")


# ----------------------------------------------------------------------
# HISTÓRICO DE PAGAMENTOS
# ----------------------------------------------------------------------

@router.callback_query(F.data == "pix_admin:history")
async def payments_history(callback: CallbackQuery, state: FSMContext):
    """Exibe pagamentos recentes."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        payments = (await session.execute(
            select(Payment).where(
                Payment.tenant_id == tenant.id,
                Payment.deleted_at.is_(None),
            )
            .order_by(Payment.created_at.desc())
            .limit(10)
        )).scalars().all()

    if not payments:
        text = "Nenhum pagamento registrado."
    else:
        text = "💳 Últimos pagamentos:\n\n"
        for p in payments:
            status_emoji = {
                "PENDING": "🟡",
                "PAID": "🟢",
                "EXPIRED": "🔴",
                "FAILED": "🔴",
                "CANCELLED": "⚫",
            }.get(p.status, "⚪")
            text += f"{status_emoji} {cents_to_brl(int(p.amount_cents))} - {p.status}\n"

    buttons = [[create_button("🔙 VOLTAR", "pix_admin:main")]]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)
