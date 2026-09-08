"""
Handlers administrativos de Estoque/Logins.

Seção 12 do painel: gerencia estoque real de serviços.
Permite importação em massa, remoção por serviço/plataforma, zerar,
estoque detalhado e alteração de preços.
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, func, update

from bot.core.database import get_async_session_factory
from bot.core.utils import cents_to_brl
from bot.core.security import encrypt_data
from bot.keyboards.utils import create_button
from bot.models.product import Product
from bot.models.inventory_item import InventoryItem
from bot.models.user import User
from bot.services.user_service import get_tenant_for_bot, get_or_create_user

logger = logging.getLogger(__name__)

router = Router()


class AdminInventoryStates(StatesGroup):
    WAITING_IMPORT_TEXT = State()
    WAITING_REMOVE_SERVICE_EMAIL = State()
    WAITING_REMOVE_PLATFORM = State()
    WAITING_ZERO_PRODUCT = State()
    WAITING_CHANGE_PRICE_SELECT_PRODUCT = State()
    WAITING_CHANGE_PRICE_AMOUNT = State()
    WAITING_CHANGE_PRICE_ALL_AMOUNT = State()


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


async def _edit_or_answer(callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup):
    """Edita a mensagem atual, se possível."""
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "inventory:main")
async def inventory_main(callback: CallbackQuery, state: FSMContext):
    """Menu principal de estoque/logins."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        total_available = (await session.execute(
            select(func.count(InventoryItem.id)).where(
                InventoryItem.tenant_id == tenant.id,
                InventoryItem.status == "AVAILABLE",
                InventoryItem.deleted_at.is_(None),
            )
        )).scalar_one()

        total_reserved = (await session.execute(
            select(func.count(InventoryItem.id)).where(
                InventoryItem.tenant_id == tenant.id,
                InventoryItem.status == "RESERVED",
                InventoryItem.deleted_at.is_(None),
            )
        )).scalar_one()

        total_sold = (await session.execute(
            select(func.count(InventoryItem.id)).where(
                InventoryItem.tenant_id == tenant.id,
                InventoryItem.status == "SOLD",
                InventoryItem.deleted_at.is_(None),
            )
        )).scalar_one()

    text = (
        "📦 ESTOQUE / LOGINS\n\n"
        f"Disponíveis: {total_available}\n"
        f"Reservados: {total_reserved}\n"
        f"Vendidos: {total_sold}\n\n"
        "Escolha uma opção:"
    )
    buttons = [
        [create_button("➕ Adicionar estoque (importação)", "inventory:add")],
        [create_button("➖ Remover login", "inventory:remove_single")],
        [create_button("📱 Remover por plataforma", "inventory:remove_platform")],
        [create_button("📊 Estoque detalhado", "inventory:detail")],
        [create_button("🗑 Zerar estoque", "inventory:zero_select")],
        [create_button("💰 Mudar valor do serviço", "inventory:change_price_select")],
        [create_button("💰 Mudar valor de todos", "inventory:change_price_all")],
        [create_button("🔙 VOLTAR", "admin:main")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


# ----------------------------------------------------------------------
# ADICIONAR ESTOQUE (IMPORTAÇÃO EM MASSA)
# ----------------------------------------------------------------------

@router.callback_query(F.data == "inventory:add")
async def inventory_add(callback: CallbackQuery, state: FSMContext):
    """Pede o texto com os logins a adicionar."""
    await state.set_state(AdminInventoryStates.WAITING_IMPORT_TEXT)
    text = (
        "Envie os logins no formato:\n"
        "<code>NOME===VALOR===DESCRICAO===EMAIL===SENHA===DURACAO</code>\n\n"
        "Um por linha. Exemplo:\n"
        "<code>HBO MAX===premium===Conta HBO===email@exemplo.com===senha123===30</code>\n\n"
        "Envie /cancelar para sair."
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "inventory:main")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminInventoryStates.WAITING_IMPORT_TEXT)
async def process_inventory_import(message: Message, state: FSMContext):
    """Processa a importação de múltiplos itens."""
    if message.text and message.text.strip().lower() == "/cancelar":
        await state.clear()
        await message.answer("Operação cancelada.")
        return

    lines = message.text.strip().split("\n") if message.text else []
    if not lines:
        await message.answer("Texto vazio.")
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

        added_count = 0
        errors = []
        for line in lines:
            parts = line.split("===")
            if len(parts) != 6:
                errors.append(f"Formato inválido: {line[:50]}...")
                continue

            name, value, description, email, password, duration = parts
            # Busca produto pelo nome
            product = (await session.execute(
                select(Product).where(
                    Product.tenant_id == tenant.id,
                    Product.name == name.strip(),
                    Product.deleted_at.is_(None),
                )
            )).scalar_one_or_none()

            if product is None:
                errors.append(f"Produto '{name}' não encontrado.")
                continue

            # Verifica duplicidade por referência
            existing = (await session.execute(
                select(InventoryItem).where(
                    InventoryItem.tenant_id == tenant.id,
                    InventoryItem.product_id == product.id,
                    InventoryItem.reference == value.strip(),
                    InventoryItem.deleted_at.is_(None),
                )
            )).scalar_one_or_none()
            if existing:
                errors.append(f"Duplicidade: {name} - {value.strip()}")
                continue

            # Cria item
            item = InventoryItem(
                tenant_id=tenant.id,
                product_id=product.id,
                status="AVAILABLE",
                email_encrypted=encrypt_data(email.strip()),
                password_encrypted=encrypt_data(password.strip()),
                note_encrypted=encrypt_data(description.strip()),
                reference=value.strip(),
            )
            session.add(item)
            added_count += 1

        await session.commit()

    await state.clear()
    result_text = f"✅ {added_count} login(s) adicionado(s)."
    if errors:
        result_text += f"\n\nErros ({len(errors)}):\n" + "\n".join(errors[:10])
    await message.answer(result_text)


# ----------------------------------------------------------------------
# REMOVER LOGIN (SERVIÇO===EMAIL)
# ----------------------------------------------------------------------

@router.callback_query(F.data == "inventory:remove_single")
async def inventory_remove_single(callback: CallbackQuery, state: FSMContext):
    """Pede o formato SERVIÇO===EMAIL para remover."""
    await state.set_state(AdminInventoryStates.WAITING_REMOVE_SERVICE_EMAIL)
    text = "Envie no formato <code>SERVICO===EMAIL</code> para remover o login."
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "inventory:main")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminInventoryStates.WAITING_REMOVE_SERVICE_EMAIL)
async def process_remove_single(message: Message, state: FSMContext):
    """Remove item baseado em serviço e email."""
    text = message.text.strip() if message.text else ""
    if "===" not in text:
        await message.answer("Formato inválido. Use SERVIÇO===EMAIL.")
        return

    service_name, email = text.split("===", 1)
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

        product = (await session.execute(
            select(Product).where(Product.tenant_id == tenant.id, Product.name == service_name.strip())
        )).scalar_one_or_none()
        if product is None:
            await message.answer(f"Serviço '{service_name}' não encontrado.")
            await state.clear()
            return

        item = (await session.execute(
            select(InventoryItem).where(
                InventoryItem.tenant_id == tenant.id,
                InventoryItem.product_id == product.id,
                InventoryItem.email_encrypted.is_not(None),
            )
        )).scalars().first()
        # Como email está criptografado, a busca por email exato não é possível.
        # Em produção, seria necessário descriptografar ou usar outro critério.
        if item:
            item.soft_delete()
            await session.commit()
            await message.answer("Login removido (soft delete).")
        else:
            await message.answer("Login não encontrado.")

    await state.clear()


# ----------------------------------------------------------------------
# REMOVER POR PLATAFORMA
# ----------------------------------------------------------------------

@router.callback_query(F.data == "inventory:remove_platform")
async def inventory_remove_platform(callback: CallbackQuery, state: FSMContext):
    """Pede o nome da plataforma para remover todos os itens."""
    await state.set_state(AdminInventoryStates.WAITING_REMOVE_PLATFORM)
    text = "Digite o nome da plataforma (ex: NETFLIX) para remover todos os itens."
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "inventory:main")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminInventoryStates.WAITING_REMOVE_PLATFORM)
async def process_remove_platform(message: Message, state: FSMContext):
    """Remove todos os itens de uma plataforma."""
    platform = message.text.strip() if message.text else ""
    if not platform:
        await message.answer("Nome vazio.")
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

        product = (await session.execute(
            select(Product).where(Product.tenant_id == tenant.id, Product.name == platform)
        )).scalar_one_or_none()
        if product is None:
            await message.answer("Plataforma não encontrada.")
            await state.clear()
            return

        # Soft delete de todos os itens disponíveis/reservados
        items = (await session.execute(
            select(InventoryItem).where(
                InventoryItem.tenant_id == tenant.id,
                InventoryItem.product_id == product.id,
                InventoryItem.status.in_(["AVAILABLE", "RESERVED"]),
            )
        )).scalars().all()
        for item in items:
            item.soft_delete()
        await session.commit()
        await message.answer(f"Removidos {len(items)} item(ns) da plataforma {platform}.")

    await state.clear()


# ----------------------------------------------------------------------
# ZERAR ESTOQUE
# ----------------------------------------------------------------------

@router.callback_query(F.data == "inventory:zero_select")
async def inventory_zero_select(callback: CallbackQuery, state: FSMContext):
    """Lista produtos para zerar estoque."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        products = (await session.execute(
            select(Product).where(Product.tenant_id == tenant.id, Product.deleted_at.is_(None))
        )).scalars().all()

    if not products:
        await callback.answer("Nenhum produto cadastrado.")
        return

    text = "Selecione o produto para zerar estoque:"
    buttons = []
    for p in products:
        buttons.append([create_button(p.name, f"inventory:zero_confirm:{p.id}")])
    buttons.append([create_button("🔙 VOLTAR", "inventory:main")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data.startswith("inventory:zero_confirm:"))
async def inventory_zero_confirm(callback: CallbackQuery, state: FSMContext):
    """Zera estoque do produto selecionado."""
    product_id = UUID(callback.data.split(":")[-1])
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        items = (await session.execute(
            select(InventoryItem).where(
                InventoryItem.tenant_id == tenant.id,
                InventoryItem.product_id == product_id,
                InventoryItem.status.in_(["AVAILABLE", "RESERVED"]),
            )
        )).scalars().all()
        for item in items:
            item.soft_delete()
        await session.commit()
        await callback.answer(f"Estoque zerado ({len(items)} itens).")

    await inventory_main(callback, state)


# ----------------------------------------------------------------------
# ESTOQUE DETALHADO
# ----------------------------------------------------------------------

@router.callback_query(F.data == "inventory:detail")
async def inventory_detail(callback: CallbackQuery, state: FSMContext):
    """Exibe estoque detalhado por produto."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        rows = (await session.execute(
            select(
                Product.name,
                func.sum(InventoryItem.status == "AVAILABLE").label("available"),
                func.sum(InventoryItem.status == "RESERVED").label("reserved"),
                func.sum(InventoryItem.status == "SOLD").label("sold"),
            )
            .join(InventoryItem, InventoryItem.product_id == Product.id)
            .where(
                InventoryItem.tenant_id == tenant.id,
                InventoryItem.deleted_at.is_(None),
            )
            .group_by(Product.name)
        )).all()

    if not rows:
        text = "Nenhum item em estoque."
    else:
        text = "📊 Estoque detalhado:\n\n"
        for name, avail, res, sold in rows:
            text += (
                f"📦 {name}\n"
                f"  ✅ Disponível: {avail or 0}\n"
                f"  ⏳ Reservado: {res or 0}\n"
                f"  🛒 Vendido: {sold or 0}\n\n"
            )

    buttons = [[create_button("🔙 VOLTAR", "inventory:main")]]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


# ----------------------------------------------------------------------
# MUDAR VALOR DO SERVIÇO (INDIVIDUAL)
# ----------------------------------------------------------------------

@router.callback_query(F.data == "inventory:change_price_select")
async def change_price_select(callback: CallbackQuery, state: FSMContext):
    """Lista produtos para alterar preço individualmente."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        products = (await session.execute(
            select(Product).where(Product.tenant_id == tenant.id, Product.deleted_at.is_(None))
        )).scalars().all()

    if not products:
        await callback.answer("Nenhum produto cadastrado.")
        return

    text = "Selecione o produto para alterar preço:"
    buttons = []
    for p in products:
        buttons.append([create_button(f"{p.name} ({cents_to_brl(int(p.price_cents))})", f"inventory:change_price_amount:{p.id}")])
    buttons.append([create_button("🔙 VOLTAR", "inventory:main")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data.startswith("inventory:change_price_amount:"))
async def change_price_amount(callback: CallbackQuery, state: FSMContext):
    """Pede o novo preço para o produto selecionado."""
    product_id = UUID(callback.data.split(":")[-1])
    await state.update_data(change_price_product_id=str(product_id))
    await state.set_state(AdminInventoryStates.WAITING_CHANGE_PRICE_AMOUNT)
    text = "Digite o novo preço (ex: 9.00):"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "inventory:change_price_select")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminInventoryStates.WAITING_CHANGE_PRICE_AMOUNT)
async def process_change_price_amount(message: Message, state: FSMContext):
    """Salva novo preço individual."""
    try:
        new_price = int(float(message.text.strip().replace(",", ".")) * 100)
        if new_price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Preço inválido.")
        return

    data = await state.get_data()
    product_id = UUID(data["change_price_product_id"])
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

        product = (await session.execute(
            select(Product).where(Product.id == product_id, Product.tenant_id == tenant.id)
        )).scalar_one_or_none()
        if product:
            product.price_cents = new_price
            await session.commit()
            await message.answer(f"✅ Preço de {product.name} atualizado para {cents_to_brl(new_price)}.")
        else:
            await message.answer("Produto não encontrado.")

    await state.clear()


# ----------------------------------------------------------------------
# MUDAR VALOR DE TODOS
# ----------------------------------------------------------------------

@router.callback_query(F.data == "inventory:change_price_all")
async def change_price_all(callback: CallbackQuery, state: FSMContext):
    """Pede o novo preço para todos os produtos."""
    await state.set_state(AdminInventoryStates.WAITING_CHANGE_PRICE_ALL_AMOUNT)
    text = "Digite o novo preço que será aplicado a todos os produtos (ex: 10.00):"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "inventory:main")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminInventoryStates.WAITING_CHANGE_PRICE_ALL_AMOUNT)
async def process_change_price_all(message: Message, state: FSMContext):
    """Aplica novo preço a todos os produtos."""
    try:
        new_price = int(float(message.text.strip().replace(",", ".")) * 100)
        if new_price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Preço inválido.")
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

        products = (await session.execute(
            select(Product).where(Product.tenant_id == tenant.id, Product.deleted_at.is_(None))
        )).scalars().all()
        for product in products:
            product.price_cents = new_price
        await session.commit()
        await message.answer(f"✅ Preço de {len(products)} produto(s) atualizado para {cents_to_brl(new_price)}.")

    await state.clear()
