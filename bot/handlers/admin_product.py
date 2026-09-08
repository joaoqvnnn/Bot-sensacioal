"""
Handlers administrativos de Produtos.

Seção 11 do painel: gerencia produtos completos.
Permite criar, editar, excluir, ativar/desativar e configurar:
nome, emoji, categoria, preço, descrição, imagem, vídeo, duração,
garantia, posição, quantidade mínima/máxima, compra múltipla, reserva,
tempo de reserva, estoque mínimo, alerta de estoque, exibição em
pesquisa/mini app, tipo de entrega, whatsapp, e-mail e status.
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

from bot.core.database import get_async_session_factory
from bot.core.utils import cents_to_brl
from bot.keyboards.utils import create_button
from bot.models.product import Product
from bot.models.category import Category
from bot.models.settings import Settings
from bot.models.user import User
from bot.services.user_service import get_tenant_for_bot, get_or_create_user

logger = logging.getLogger(__name__)

router = Router()


class AdminProductStates(StatesGroup):
    WAITING_NAME = State()
    WAITING_EMOJI = State()
    WAITING_CATEGORY = State()
    WAITING_PRICE = State()
    WAITING_DESCRIPTION = State()
    WAITING_IMAGE_URL = State()
    WAITING_VIDEO_URL = State()
    WAITING_DURATION = State()
    WAITING_GUARANTEE = State()
    WAITING_POSITION = State()
    WAITING_MIN_QTY = State()
    WAITING_MAX_QTY = State()
    WAITING_RESERVE_MINUTES = State()
    WAITING_MIN_STOCK_ALERT = State()
    WAITING_DELIVERY_METHOD = State()
    WAITING_EDIT_FIELD = State()


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


async def _get_products(session, tenant_id: UUID):
    """Lista produtos do tenant."""
    stmt = select(Product).where(
        Product.tenant_id == tenant_id,
        Product.deleted_at.is_(None),
    ).order_by(Product.position.asc(), Product.name.asc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.callback_query(F.data == "products:main")
async def products_main(callback: CallbackQuery, state: FSMContext):
    """Menu principal de produtos."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        products = await _get_products(session, tenant.id)

    if not products:
        text = "📦 PRODUTOS\n\nNenhum produto cadastrado."
    else:
        text = "📦 PRODUTOS\n\nProdutos:\n"
        for p in products:
            status = "🟢" if p.is_active else "🔴"
            text += f"{status} {p.name} - {cents_to_brl(int(p.price_cents))}\n"

    text += "\nEscolha uma ação:"

    buttons = [
        [create_button("➕ Criar produto", "products:create_start")],
        [create_button("✏️ Editar produto", "products:edit_select")],
        [create_button("🗑 Excluir produto", "products:delete_select")],
        [create_button("Ativar/Desativar", "products:toggle_select")],
        [create_button("🔙 VOLTAR", "admin:main")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


# ----------------------------------------------------------------------
# CRIAR PRODUTO
# ----------------------------------------------------------------------

@router.callback_query(F.data == "products:create_start")
async def product_create_start(callback: CallbackQuery, state: FSMContext):
    """Inicia criação de produto solicitando nome."""
    await state.set_state(AdminProductStates.WAITING_NAME)
    text = "Digite o nome do novo produto:"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "products:main")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminProductStates.WAITING_NAME)
async def process_product_name(message: Message, state: FSMContext):
    """Recebe nome e pede emoji."""
    name = message.text.strip()
    if not name:
        await message.answer("Nome inválido.")
        return

    await state.update_data(product_name=name)
    await state.set_state(AdminProductStates.WAITING_EMOJI)
    await message.answer("Digite um emoji para o produto (ou '-' para sem emoji):")


@router.message(AdminProductStates.WAITING_EMOJI)
async def process_product_emoji(message: Message, state: FSMContext):
    """Recebe emoji e pede preço."""
    emoji = message.text.strip()
    if emoji == "-":
        emoji = None

    await state.update_data(product_emoji=emoji)
    await state.set_state(AdminProductStates.WAITING_PRICE)
    await message.answer("Digite o preço do produto (ex: 8.00):")


@router.message(AdminProductStates.WAITING_PRICE)
async def process_product_price(message: Message, state: FSMContext):
    """Recebe preço e pede descrição."""
    try:
        price_cents = int(float(message.text.strip().replace(",", ".")) * 100)
        if price_cents <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Preço inválido.")
        return

    await state.update_data(product_price_cents=price_cents)
    await state.set_state(AdminProductStates.WAITING_DESCRIPTION)
    await message.answer("Digite a descrição do produto (ou '-' para sem descrição):")


@router.message(AdminProductStates.WAITING_DESCRIPTION)
async def process_product_description(message: Message, state: FSMContext):
    """Recebe descrição e pede duração."""
    description = message.text.strip()
    if description == "-":
        description = None

    await state.update_data(product_description=description)
    await state.set_state(AdminProductStates.WAITING_DURATION)
    await message.answer("Digite a duração em dias (ex: 30):")


@router.message(AdminProductStates.WAITING_DURATION)
async def process_product_duration(message: Message, state: FSMContext):
    """Recebe duração e pede garantia."""
    try:
        duration_days = int(message.text.strip())
        if duration_days < 0:
            raise ValueError
    except ValueError:
        await message.answer("Duração inválida.")
        return

    await state.update_data(product_duration_days=duration_days)
    await state.set_state(AdminProductStates.WAITING_GUARANTEE)
    await message.answer("Digite a garantia em dias (ex: 30):")


@router.message(AdminProductStates.WAITING_GUARANTEE)
async def process_product_guarantee(message: Message, state: FSMContext):
    """Recebe garantia e pergunta categoria."""
    try:
        guarantee_days = int(message.text.strip())
        if guarantee_days < 0:
            raise ValueError
    except ValueError:
        await message.answer("Garantia inválida.")
        return

    await state.update_data(product_guarantee_days=guarantee_days)

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

        categories = (await session.execute(
            select(Category).where(
                Category.tenant_id == tenant.id,
                Category.deleted_at.is_(None),
            )
        )).scalars().all()

    if not categories:
        await _finish_product_creation(message, state, category_id=None)
        return

    await state.set_state(AdminProductStates.WAITING_CATEGORY)
    text = "Selecione a categoria (ou '-' para sem categoria):"
    buttons = []
    for cat in categories:
        buttons.append([create_button(f"{cat.emoji or ''} {cat.name}", f"products:category_select:{cat.id}")])
    buttons.append([create_button("Sem categoria", "products:category_select:none")])
    buttons.append([create_button("🔙 CANCELAR", "products:main")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(AdminProductStates.WAITING_CATEGORY, F.data.startswith("products:category_select:"))
async def process_category_select(callback: CallbackQuery, state: FSMContext):
    """Recebe categoria e finaliza criação."""
    category_str = callback.data.split(":")[-1]
    category_id = None if category_str == "none" else UUID(category_str)
    await _finish_product_creation(callback, state, category_id)


async def _finish_product_creation(event, state: FSMContext, category_id: Optional[UUID]):
    """Cria o produto com os dados coletados e configurações default."""
    data = await state.get_data()

    if isinstance(event, CallbackQuery):
        message = event.message
        tenant, admin = await _get_tenant_and_user_from_callback(event)
    else:
        message = event
        tenant, admin = await _get_tenant_and_user_from_message(event)

    if tenant is None:
        await message.answer("Sistema indisponível.")
        await state.clear()
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, admin.id):
            await message.answer("Acesso negado.")
            await state.clear()
            return

        # Posição = última + 1
        max_pos = (await session.execute(
            select(func.max(Product.position)).where(Product.tenant_id == tenant.id)
        )).scalar() or 0

        product = Product(
            tenant_id=tenant.id,
            category_id=category_id,
            name=data["product_name"],
            description=data.get("product_description"),
            price_cents=data["product_price_cents"],
            duration_days=data["product_duration_days"],
            guarantee_days=data["product_guarantee_days"],
            is_active=True,
            position=max_pos + 1,
            max_per_user=0,  # será configurado depois via edição
        )
        session.add(product)
        await session.commit()

    await state.clear()
    await message.answer("✅ Produto criado com sucesso!")


# ----------------------------------------------------------------------
# SELEÇÃO DE PRODUTO PARA EDIÇÃO
# ----------------------------------------------------------------------

@router.callback_query(F.data == "products:edit_select")
async def product_edit_select(callback: CallbackQuery, state: FSMContext):
    """Lista produtos para edição."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return
        products = await _get_products(session, tenant.id)

    if not products:
        await callback.answer("Nenhum produto cadastrado.")
        return

    text = "Selecione o produto para editar:"
    buttons = []
    for p in products:
        buttons.append([create_button(p.name, f"products:edit_menu:{p.id}")])
    buttons.append([create_button("🔙 VOLTAR", "products:main")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data.startswith("products:edit_menu:"))
async def product_edit_menu(callback: CallbackQuery, state: FSMContext):
    """Menu de edição de um produto específico."""
    product_id = UUID(callback.data.split(":")[-1])
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        product = (await session.execute(
            select(Product).where(Product.id == product_id, Product.tenant_id == tenant.id)
        )).scalar_one_or_none()
        if product is None:
            await callback.answer("Produto não encontrado.")
            return

    await state.update_data(edit_product_id=str(product.id))

    # Carrega configurações extras de Settings (para campos não mapeados no modelo)
    extras = {}
    for key in ["product_emoji", "product_image_url", "product_video_url",
                "product_allow_multi", "product_reserve_enabled",
                "product_reserve_minutes", "product_min_stock_alert",
                "product_show_in_search", "product_show_in_miniapp",
                "product_delivery_method", "product_whatsapp_config", "product_email_config"]:
        extras[key] = await _get_setting(session, tenant.id, key) if product else None

    text = (
        f"✏️ Editando: <b>{product.name}</b>\n\n"
        f"💰 Preço: {cents_to_brl(int(product.price_cents))}\n"
        f"📝 Descrição: {product.description or 'N/A'}\n"
        f"⏳ Duração: {product.duration_days} dias\n"
        f"🛡 Garantia: {product.guarantee_days} dias\n"
        f"Status: {'🟢 Ativo' if product.is_active else '🔴 Inativo'}\n"
        f"Posição: {product.position}\n"
        "Escolha o campo para editar:"
    )
    buttons = [
        [create_button("📝 Nome", "products:edit_name")],
        [create_button("💰 Preço", "products:edit_price")],
        [create_button("📝 Descrição", "products:edit_description")],
        [create_button("⏳ Duração", "products:edit_duration")],
        [create_button("🛡 Garantia", "products:edit_guarantee")],
        [create_button("🔢 Posição", "products:edit_position")],
        [create_button("🏷️ Emoji", "products:edit_emoji")],
        [create_button("🖼️ Imagem", "products:edit_image")],
        [create_button("🎥 Vídeo", "products:edit_video")],
        [create_button("👥 Qtd mínima", "products:edit_min_qty")],
        [create_button("👥 Qtd máxima", "products:edit_max_qty")],
        [create_button("🔁 Compra múltipla", "products:toggle_multi")],
        [create_button("🔒 Reserva", "products:toggle_reserve")],
        [create_button("⏱ Tempo de reserva", "products:edit_reserve_minutes")],
        [create_button("🔔 Estoque mínimo", "products:edit_min_stock_alert")],
        [create_button("🔎 Exibir em pesquisa", "products:toggle_search")],
        [create_button("📱 Exibir Mini App", "products:toggle_miniapp")],
        [create_button("📦 Tipo de entrega", "products:edit_delivery")],
        [create_button("💬 Config WhatsApp", "products:edit_whatsapp")],
        [create_button("📧 Config Email", "products:edit_email")],
        [create_button("🔙 VOLTAR", "products:edit_select")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


# ----------------------------------------------------------------------
# EDIÇÃO DE CAMPOS SIMPLES
# ----------------------------------------------------------------------

async def _edit_product_field(callback: CallbackQuery, state: FSMContext, field: str, title: str):
    """Inicia edição de um campo simples do produto."""
    await state.set_state(AdminProductStates.WAITING_EDIT_FIELD)
    await state.update_data(edit_field=field)
    text = f"Digite o novo valor para <b>{title}</b>:"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "products:edit_menu")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "products:edit_name")
async def edit_name(callback: CallbackQuery, state: FSMContext):
    await _edit_product_field(callback, state, "name", "nome")


@router.callback_query(F.data == "products:edit_price")
async def edit_price(callback: CallbackQuery, state: FSMContext):
    await _edit_product_field(callback, state, "price", "preço")


@router.callback_query(F.data == "products:edit_description")
async def edit_description(callback: CallbackQuery, state: FSMContext):
    await _edit_product_field(callback, state, "description", "descrição")


@router.callback_query(F.data == "products:edit_duration")
async def edit_duration(callback: CallbackQuery, state: FSMContext):
    await _edit_product_field(callback, state, "duration", "duração (dias)")


@router.callback_query(F.data == "products:edit_guarantee")
async def edit_guarantee(callback: CallbackQuery, state: FSMContext):
    await _edit_product_field(callback, state, "guarantee", "garantia (dias)")


@router.callback_query(F.data == "products:edit_position")
async def edit_position(callback: CallbackQuery, state: FSMContext):
    await _edit_product_field(callback, state, "position", "posição")


@router.callback_query(F.data == "products:edit_emoji")
async def edit_emoji(callback: CallbackQuery, state: FSMContext):
    await _edit_product_field(callback, state, "emoji", "emoji")


@router.callback_query(F.data == "products:edit_image")
async def edit_image(callback: CallbackQuery, state: FSMContext):
    await _edit_product_field(callback, state, "image", "URL da imagem")


@router.callback_query(F.data == "products:edit_video")
async def edit_video(callback: CallbackQuery, state: FSMContext):
    await _edit_product_field(callback, state, "video", "URL do vídeo")


@router.callback_query(F.data == "products:edit_min_qty")
async def edit_min_qty(callback: CallbackQuery, state: FSMContext):
    await _edit_product_field(callback, state, "min_qty", "quantidade mínima")


@router.callback_query(F.data == "products:edit_max_qty")
async def edit_max_qty(callback: CallbackQuery, state: FSMContext):
    await _edit_product_field(callback, state, "max_qty", "quantidade máxima")


@router.callback_query(F.data == "products:edit_reserve_minutes")
async def edit_reserve_minutes(callback: CallbackQuery, state: FSMContext):
    await _edit_product_field(callback, state, "reserve_minutes", "tempo de reserva (minutos)")


@router.callback_query(F.data == "products:edit_min_stock_alert")
async def edit_min_stock_alert(callback: CallbackQuery, state: FSMContext):
    await _edit_product_field(callback, state, "min_stock_alert", "estoque mínimo para alerta")


@router.callback_query(F.data == "products:edit_delivery")
async def edit_delivery(callback: CallbackQuery, state: FSMContext):
    await _edit_product_field(callback, state, "delivery", "tipo de entrega (TELEGRAM, WHATSAPP, EMAIL)")


@router.callback_query(F.data == "products:edit_whatsapp")
async def edit_whatsapp(callback: CallbackQuery, state: FSMContext):
    await _edit_product_field(callback, state, "whatsapp_config", "configuração WhatsApp")


@router.callback_query(F.data == "products:edit_email")
async def edit_email(callback: CallbackQuery, state: FSMContext):
    await _edit_product_field(callback, state, "email_config", "configuração e-mail")


@router.message(AdminProductStates.WAITING_EDIT_FIELD)
async def process_edit_field(message: Message, state: FSMContext):
    """Salva o novo valor do campo editado."""
    value = message.text.strip()
    data = await state.get_data()
    field = data.get("edit_field")
    product_id = UUID(data.get("edit_product_id"))

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
        if product is None:
            await message.answer("Produto não encontrado.")
            await state.clear()
            return

        # Mapeia campo para atualização
        if field == "name":
            product.name = value
        elif field == "price":
            try:
                product.price_cents = int(float(value.replace(",", ".")) * 100)
            except ValueError:
                await message.answer("Preço inválido.")
                await state.clear()
                return
        elif field == "description":
            product.description = value
        elif field == "duration":
            product.duration_days = int(value)
        elif field == "guarantee":
            product.guarantee_days = int(value)
        elif field == "position":
            product.position = int(value)
        elif field in ("emoji", "image", "video", "min_qty", "max_qty", "reserve_minutes", "min_stock_alert", "delivery", "whatsapp_config", "email_config"):
            # Salva em Settings (chave composta)
            key = f"product_{field}"
            await _set_setting(session, tenant.id, key, value)
        else:
            await message.answer("Campo desconhecido.")
            await state.clear()
            return

        await session.commit()
        await message.answer("✅ Campo atualizado.")

    await state.clear()


# ----------------------------------------------------------------------
# TOGGLES
# ----------------------------------------------------------------------

async def _toggle_product_bool_setting(callback: CallbackQuery, state: FSMContext, key: str, label: str):
    """Alterna uma configuração booleana armazenada em Settings."""
    data = await state.get_data()
    product_id = UUID(data.get("edit_product_id"))
    tenant, admin = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, admin.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        current = await _get_setting(session, tenant.id, key) or "false"
        new_val = "false" if current == "true" else "true"
        await _set_setting(session, tenant.id, key, new_val)

    await callback.answer(f"{label} {'ativado' if new_val == 'true' else 'desativado'}.")
    await product_edit_menu(callback, state)


@router.callback_query(F.data == "products:toggle_multi")
async def toggle_multi(callback: CallbackQuery, state: FSMContext):
    await _toggle_product_bool_setting(callback, state, "product_allow_multi", "Compra múltipla")


@router.callback_query(F.data == "products:toggle_reserve")
async def toggle_reserve(callback: CallbackQuery, state: FSMContext):
    await _toggle_product_bool_setting(callback, state, "product_reserve_enabled", "Reserva")


@router.callback_query(F.data == "products:toggle_search")
async def toggle_search(callback: CallbackQuery, state: FSMContext):
    await _toggle_product_bool_setting(callback, state, "product_show_in_search", "Exibir em pesquisa")


@router.callback_query(F.data == "products:toggle_miniapp")
async def toggle_miniapp(callback: CallbackQuery, state: FSMContext):
    await _toggle_product_bool_setting(callback, state, "product_show_in_miniapp", "Exibir no Mini App")


# ----------------------------------------------------------------------
# EXCLUSÃO
# ----------------------------------------------------------------------

@router.callback_query(F.data == "products:delete_select")
async def product_delete_select(callback: CallbackQuery, state: FSMContext):
    """Lista produtos para exclusão."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return
        products = await _get_products(session, tenant.id)

    if not products:
        await callback.answer("Nenhum produto cadastrado.")
        return

    text = "Selecione o produto para excluir:"
    buttons = []
    for p in products:
        buttons.append([create_button(p.name, f"products:delete_confirm:{p.id}")])
    buttons.append([create_button("🔙 VOLTAR", "products:main")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data.startswith("products:delete_confirm:"))
async def product_delete_confirm(callback: CallbackQuery, state: FSMContext):
    """Exclui produto (soft delete)."""
    product_id = UUID(callback.data.split(":")[-1])
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        product = (await session.execute(
            select(Product).where(Product.id == product_id, Product.tenant_id == tenant.id)
        )).scalar_one_or_none()
        if product:
            product.soft_delete()
            await session.commit()
            await callback.answer(f"Produto '{product.name}' excluído.")
        else:
            await callback.answer("Produto não encontrado.")

    await products_main(callback, state)


# ----------------------------------------------------------------------
# TOGGLE STATUS
# ----------------------------------------------------------------------

@router.callback_query(F.data == "products:toggle_select")
async def product_toggle_select(callback: CallbackQuery, state: FSMContext):
    """Lista produtos para alternar status."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return
        products = await _get_products(session, tenant.id)

    if not products:
        await callback.answer("Nenhum produto cadastrado.")
        return

    text = "Selecione o produto para alternar status:"
    buttons = []
    for p in products:
        status = "🟢" if p.is_active else "🔴"
        buttons.append([create_button(f"{status} {p.name}", f"products:toggle:{p.id}")])
    buttons.append([create_button("🔙 VOLTAR", "products:main")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data.startswith("products:toggle:"))
async def product_toggle(callback: CallbackQuery, state: FSMContext):
    """Alterna status ativo/inativo do produto."""
    product_id = UUID(callback.data.split(":")[-1])
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        product = (await session.execute(
            select(Product).where(Product.id == product_id, Product.tenant_id == tenant.id)
        )).scalar_one_or_none()
        if product:
            product.is_active = not product.is_active
            await session.commit()
            await callback.answer(f"Produto '{product.name}' {'ativado' if product.is_active else 'desativado'}.")
        else:
            await callback.answer("Produto não encontrado.")

    await product_toggle_select(callback, state)
