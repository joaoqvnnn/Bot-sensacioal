"""
Handlers administrativos de produtos e estoque.

Permite ao administrador:
- Adicionar/remover produtos
- Adicionar/remover logins (itens de estoque)
- Listar estoque detalhado
- Zerar estoque de um produto
- Alterar preço de um produto

Tudo com edição da mesma mensagem, botões de voltar e dados reais.
"""

import logging
from typing import Optional
from uuid import UUID

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, func

from bot.core.database import get_async_session_factory
from bot.core.utils import cents_to_brl
from bot.keyboards.utils import create_button
from bot.models.product import Product
from bot.models.inventory_item import InventoryItem
from bot.models.user import User
from bot.models.tenant import Tenant
from bot.services.user_service import get_tenant_for_bot, get_or_create_user
from bot.services.inventory_service import add_stock_items, get_available_count

logger = logging.getLogger(__name__)

router = Router()


class AdminStockStates(StatesGroup):
    WAITING_PRODUCT_NAME = State()
    WAITING_PRODUCT_PRICE = State()
    WAITING_PRODUCT_CATEGORY = State()
    WAITING_STOCK_DATA = State()
    WAITING_REMOVE_PRODUCT_ID = State()
    WAITING_REMOVE_STOCK_DATA = State()
    WAITING_PRICE_UPDATE = State()


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


async def _is_admin(session, tenant_id, user_id) -> bool:
    """Verifica se o usuário é admin/dono."""
    from bot.models.admin_user import AdminUser

    user = (await session.execute(
        select(User).where(User.id == user_id, User.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if user and (user.is_owner or user.is_admin):
        return True
    admin = (await session.execute(
        select(AdminUser).where(
            AdminUser.tenant_id == tenant_id,
            AdminUser.user_id == user_id,
            AdminUser.is_active == True,
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


@router.callback_query(F.data == "admin:manage_stock")
async def manage_stock(callback: CallbackQuery, state: FSMContext):
    """Menu de gerenciamento de produtos e estoque."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        product_count = (await session.execute(
            select(func.count(Product.id)).where(
                Product.tenant_id == tenant.id,
                Product.deleted_at.is_(None),
            )
        )).scalar_one()

        total_stock = (await session.execute(
            select(func.count(InventoryItem.id)).where(
                InventoryItem.tenant_id == tenant.id,
                InventoryItem.status == "AVAILABLE",
                InventoryItem.deleted_at.is_(None),
            )
        )).scalar_one()

    text = (
        "📦 CONFIGURAR LOGINS\n\n"
        f"LOGINS NO ESTOQUE: {total_stock}\n"
        f"Produtos cadastrados: {product_count}\n\n"
        "Use os botões abaixo:"
    )
    buttons = [
        [create_button("➕ ADICIONAR PRODUTO", "admin:add_product")],
        [create_button("➕ ADICIONAR LOGIN", "admin:add_stock")],
        [create_button("➖ REMOVER LOGIN", "admin:remove_stock")],
        [create_button("📊 ESTOQUE DETALHADO", "admin:stock_detail")],
        [create_button("🗑 ZERAR ESTOQUE", "admin:zero_stock")],
        [create_button("💰 MUDAR VALOR DO SERVIÇO", "admin:change_price")],
        [create_button("🔙 VOLTAR", "admin:main")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "admin:add_product")
async def add_product(callback: CallbackQuery, state: FSMContext):
    """Pede nome do novo produto."""
    await state.set_state(AdminStockStates.WAITING_PRODUCT_NAME)
    text = "Digite o nome do novo produto:"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "admin:manage_stock")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminStockStates.WAITING_PRODUCT_NAME)
async def process_product_name(message: Message, state: FSMContext):
    """Recebe nome e pede preço."""
    name = message.text.strip() if message.text else ""
    if not name:
        await message.answer("Nome inválido.")
        return

    await state.update_data(product_name=name)
    await state.set_state(AdminStockStates.WAITING_PRODUCT_PRICE)
    await message.answer("Digite o preço do produto (ex: 8.00):")


@router.message(AdminStockStates.WAITING_PRODUCT_PRICE)
async def process_product_price(message: Message, state: FSMContext):
    """Recebe preço e cria produto."""
    try:
        price_cents = int(float(message.text.replace(",", ".")) * 100)
    except ValueError:
        await message.answer("Preço inválido. Use formato como 8.00 ou 10,50.")
        return

    data = await state.get_data()
    name = data.get("product_name")

    tenant, user = await _get_tenant_and_user_from_message(message)
    if tenant is None:
        await message.answer("Sistema indisponível.")
        await state.clear()
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await message.answer("Acesso negado.")
            await state.clear()
            return

        product = Product(
            tenant_id=tenant.id,
            name=name,
            price_cents=price_cents,
            is_active=True,
            duration_days=30,
            guarantee_days=30,
        )
        session.add(product)
        await session.commit()
        await session.refresh(product)

    await state.clear()
    await message.answer(f"✅ Produto '{name}' criado com sucesso! Preço: {cents_to_brl(price_cents)}")


@router.callback_query(F.data == "admin:add_stock")
async def add_stock(callback: CallbackQuery, state: FSMContext):
    """Pede dados dos logins a adicionar."""
    await state.set_state(AdminStockStates.WAITING_STOCK_DATA)
    text = (
        "Envie os logins no formato:\n"
        "NOME===VALOR===DESCRICAO===EMAIL===SENHA===DURACAO\n"
        "Um por linha.\n\n"
        "Exemplo:\n"
        "HBO MAX===premium===Conta HBO===email@exemplo.com===senha123===30\n"
        "Envie /cancelar para sair."
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "admin:manage_stock")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminStockStates.WAITING_STOCK_DATA)
async def process_stock_data(message: Message, state: FSMContext):
    """Processa múltiplos logins e adiciona ao estoque."""
    if message.text and message.text.strip().lower() == "/cancelar":
        await state.clear()
        await message.answer("Operação cancelada.")
        return

    lines = message.text.strip().split("\n") if message.text else []
    if not lines:
        await message.answer("Formato inválido.")
        return

    tenant, user = await _get_tenant_and_user_from_message(message)
    if tenant is None:
        await message.answer("Sistema indisponível.")
        await state.clear()
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await message.answer("Acesso negado.")
            await state.clear()
            return

        items_data = []
        for line in lines:
            parts = line.split("===")
            if len(parts) != 6:
                continue
            name, value, description, email, password, duration = parts
            # Encontrar produto pelo nome
            product = (await session.execute(
                select(Product).where(
                    Product.tenant_id == tenant.id,
                    Product.name == name.strip(),
                    Product.deleted_at.is_(None),
                )
            )).scalar_one_or_none()
            if product is None:
                # Criar produto automaticamente? Não, apenas alertar.
                await message.answer(f"Produto '{name}' não encontrado. Crie o produto primeiro.")
                await state.clear()
                return

            # Criptografar dados sensíveis (usar security.encrypt_data)
            from bot.core.security import encrypt_data
            items_data.append({
                "product_id": product.id,
                "email_encrypted": encrypt_data(email.strip()),
                "password_encrypted": encrypt_data(password.strip()),
                "note_encrypted": encrypt_data(description.strip()),
                "reference": value.strip(),
            })

        # Adicionar itens
        from bot.services.inventory_service import add_stock_items
        for data in items_data:
            await add_stock_items(session, tenant.id, data["product_id"], [{
                "email_encrypted": data["email_encrypted"],
                "password_encrypted": data["password_encrypted"],
                "note_encrypted": data["note_encrypted"],
                "reference": data["reference"],
            }])

        await state.clear()
        await message.answer(f"✅ {len(items_data)} login(s) adicionado(s) ao estoque.")


@router.callback_query(F.data == "admin:stock_detail")
async def stock_detail(callback: CallbackQuery, state: FSMContext):
    """Mostra estoque detalhado por produto."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        # Conta por status e produto
        stmt = (
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
        )
        result = await session.execute(stmt)
        rows = result.all()

    if not rows:
        text = "Nenhum item em estoque."
    else:
        text = "📊 Estoque detalhado:\n\n"
        for name, available, reserved, sold in rows:
            text += (
                f"📦 {name}\n"
                f"  ✅ Disponível: {available or 0}\n"
                f"  ⏳ Reservado: {reserved or 0}\n"
                f"  🛒 Vendido: {sold or 0}\n\n"
            )

    buttons = [[create_button("🔙 VOLTAR", "admin:manage_stock")]]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "admin:zero_stock")
async def zero_stock(callback: CallbackQuery, state: FSMContext):
    """Pede ID do produto para zerar estoque."""
    # Por simplicidade, lista produtos com ID para escolha
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        products = (await session.execute(
            select(Product).where(
                Product.tenant_id == tenant.id,
                Product.deleted_at.is_(None),
            )
        )).scalars().all()

    if not products:
        text = "Nenhum produto cadastrado."
    else:
        text = "Selecione o produto para zerar estoque:\n\n"
        buttons = []
        for p in products:
            buttons.append([create_button(p.name, f"admin:zero_stock_confirm:{p.id}")])
        buttons.append([create_button("🔙 VOLTAR", "admin:manage_stock")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await _edit_or_answer(callback, text, keyboard)
        return


@router.callback_query(F.data.startswith("admin:zero_stock_confirm:"))
async def zero_stock_confirm(callback: CallbackQuery, state: FSMContext):
    """Confirma e zera estoque de um produto."""
    product_id = callback.data.split(":")[-1]
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        # Remove itens AVAILABLE e RESERVED (mantém SOLD para histórico)
        from sqlalchemy import update
        await session.execute(
            update(InventoryItem)
            .where(
                InventoryItem.tenant_id == tenant.id,
                InventoryItem.product_id == UUID(product_id),
                InventoryItem.status.in_(["AVAILABLE", "RESERVED"]),
            )
            .values(status="CANCELLED", deleted_at=datetime.now(timezone.utc))
        )
        await session.commit()

    await callback.answer("Estoque zerado!")
    await manage_stock(callback, state)


@router.callback_query(F.data == "admin:change_price")
async def change_price(callback: CallbackQuery, state: FSMContext):
    """Pede ID do produto e novo preço."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        products = (await session.execute(
            select(Product).where(
                Product.tenant_id == tenant.id,
                Product.deleted_at.is_(None),
            )
        )).scalars().all()

    if not products:
        text = "Nenhum produto cadastrado."
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[create_button("🔙 VOLTAR", "admin:manage_stock")]])
        await _edit_or_answer(callback, text, keyboard)
        return

    text = "Selecione o produto para alterar preço:\n\n"
    buttons = []
    for p in products:
        buttons.append([create_button(f"{p.name} ({cents_to_brl(int(p.price_cents))})", f"admin:change_price_select:{p.id}")])
    buttons.append([create_button("🔙 VOLTAR", "admin:manage_stock")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data.startswith("admin:change_price_select:"))
async def change_price_select(callback: CallbackQuery, state: FSMContext):
    """Pede novo preço para o produto selecionado."""
    product_id = callback.data.split(":")[-1]
    await state.update_data(product_id=product_id)
    await state.set_state(AdminStockStates.WAITING_PRICE_UPDATE)
    text = "Digite o novo preço (ex: 9.00):"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "admin:change_price")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminStockStates.WAITING_PRICE_UPDATE)
async def process_price_update(message: Message, state: FSMContext):
    """Salva novo preço."""
    try:
        new_price_cents = int(float(message.text.replace(",", ".")) * 100)
    except ValueError:
        await message.answer("Preço inválido.")
        return

    data = await state.get_data()
    product_id = UUID(data["product_id"])

    tenant, user = await _get_tenant_and_user_from_message(message)
    if tenant is None:
        await message.answer("Sistema indisponível.")
        await state.clear()
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await message.answer("Acesso negado.")
            await state.clear()
            return

        product = (await session.execute(
            select(Product).where(Product.id == product_id, Product.tenant_id == tenant.id)
        )).scalar_one_or_none()
        if product:
            product.price_cents = new_price_cents
            await session.commit()
            await message.answer(f"✅ Preço atualizado para {cents_to_brl(new_price_cents)}.")
        else:
            await message.answer("Produto não encontrado.")

    await state.clear()
