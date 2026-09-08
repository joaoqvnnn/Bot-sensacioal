"""
Handlers administrativos de Configuração dos Botões.

Seção 3 do painel: gerencia layouts e botões individuais.
Permite criar, editar, excluir e ativar/desativar layouts,
e dentro de cada layout, adicionar, editar, remover e reordenar botões.

Os layouts são armazenados na tabela KeyboardLayout.
"""

import json
import logging
from typing import Optional, List
from uuid import UUID

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select

from bot.core.database import get_async_session_factory
from bot.keyboards.utils import create_button
from bot.models.keyboard_layout import KeyboardLayout
from bot.models.user import User
from bot.services.user_service import get_tenant_for_bot, get_or_create_user

logger = logging.getLogger(__name__)

router = Router()


class AdminButtonsStates(StatesGroup):
    WAITING_LAYOUT_CODE = State()
    WAITING_BUTTON_TEXT = State()
    WAITING_BUTTON_CALLBACK = State()
    WAITING_BUTTON_URL = State()
    WAITING_BUTTON_EMOJI = State()
    WAITING_ROW_WIDTH = State()
    WAITING_BUTTON_SELECT_FOR_EDIT = State()
    WAITING_BUTTON_NEW_TEXT = State()
    WAITING_BUTTON_NEW_CALLBACK = State()
    WAITING_BUTTON_NEW_URL = State()


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


async def _get_layouts(session, tenant_id: UUID) -> List[KeyboardLayout]:
    """Lista layouts de teclado do tenant."""
    stmt = select(KeyboardLayout).where(
        KeyboardLayout.tenant_id == tenant_id,
        KeyboardLayout.deleted_at.is_(None),
    ).order_by(KeyboardLayout.code)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _get_layout_by_id(session, tenant_id: UUID, layout_id: UUID) -> Optional[KeyboardLayout]:
    """Busca layout pelo ID."""
    stmt = select(KeyboardLayout).where(
        KeyboardLayout.tenant_id == tenant_id,
        KeyboardLayout.id == layout_id,
        KeyboardLayout.deleted_at.is_(None),
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


# ----------------------------------------------------------------------
# MENU PRINCIPAL
# ----------------------------------------------------------------------

@router.callback_query(F.data == "admin:buttons")
async def show_buttons_menu(callback: CallbackQuery, state: FSMContext):
    """Menu principal de configuração de botões."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        layouts = await _get_layouts(session, tenant.id)

    if not layouts:
        text = "🔘 CONFIGURAÇÃO DOS BOTÕES\n\nNenhum layout cadastrado."
    else:
        text = "🔘 CONFIGURAÇÃO DOS BOTÕES\n\nLayouts disponíveis:\n"
        for layout in layouts:
            status = "🟢" if layout.is_active else "🔴"
            text += f"{status} <b>{layout.code}</b> (row_width: {layout.row_width})\n"

    text += "\nEscolha uma opção:"

    buttons = [
        [create_button("➕ Criar layout", "kbb:create_layout")],
        [create_button("✏️ Editar layout", "kbb:select_layout_edit")],
        [create_button("🗑 Excluir layout", "kbb:select_layout_delete")],
        [create_button("Ativar/Desativar layout", "kbb:select_layout_toggle")],
        [create_button("🔙 VOLTAR", "admin:main")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


# ----------------------------------------------------------------------
# CRIAR LAYOUT
# ----------------------------------------------------------------------

@router.callback_query(F.data == "kbb:create_layout")
async def create_layout_start(callback: CallbackQuery, state: FSMContext):
    """Inicia criação de novo layout."""
    await state.set_state(AdminButtonsStates.WAITING_LAYOUT_CODE)
    text = "Digite o código do novo layout (ex: main_menu, catalog, product):"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "admin:buttons")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminButtonsStates.WAITING_LAYOUT_CODE)
async def process_layout_code(message: Message, state: FSMContext):
    """Recebe código e pede row_width."""
    code = message.text.strip().lower()
    if not code:
        await message.answer("Código inválido.")
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

        # Verifica duplicidade
        existing = (await session.execute(
            select(KeyboardLayout).where(
                KeyboardLayout.tenant_id == tenant.id,
                KeyboardLayout.code == code,
                KeyboardLayout.deleted_at.is_(None),
            )
        )).scalar_one_or_none()
        if existing:
            await message.answer("Já existe layout com esse código.")
            await state.clear()
            return

    await state.update_data(layout_code=code)
    await state.set_state(AdminButtonsStates.WAITING_ROW_WIDTH)
    await message.answer("Digite a quantidade de botões por linha (ex: 2):")


@router.message(AdminButtonsStates.WAITING_ROW_WIDTH)
async def process_row_width(message: Message, state: FSMContext):
    """Recebe row_width e cria layout vazio."""
    try:
        row_width = int(message.text.strip())
        if row_width < 1 or row_width > 5:
            raise ValueError
    except ValueError:
        await message.answer("Valor inválido. Digite um número entre 1 e 5.")
        return

    data = await state.get_data()
    code = data.get("layout_code")

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

        layout = KeyboardLayout(
            tenant_id=tenant.id,
            code=code,
            buttons_json=json.dumps([], ensure_ascii=False),
            row_width=row_width,
            is_active=True,
        )
        session.add(layout)
        await session.commit()

    await state.clear()
    await message.answer(f"✅ Layout '{code}' criado com sucesso!")


# ----------------------------------------------------------------------
# SELEÇÃO DE LAYOUT PARA EDIÇÃO
# ----------------------------------------------------------------------

@router.callback_query(F.data == "kbb:select_layout_edit")
async def select_layout_edit(callback: CallbackQuery, state: FSMContext):
    """Lista layouts para editar."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return
        layouts = await _get_layouts(session, tenant.id)

    if not layouts:
        await callback.answer("Nenhum layout cadastrado.")
        return

    text = "Selecione o layout para editar:"
    buttons = []
    for layout in layouts:
        buttons.append([create_button(layout.code, f"kbb:edit_layout_menu:{layout.id}")])
    buttons.append([create_button("🔙 VOLTAR", "admin:buttons")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data.startswith("kbb:edit_layout_menu:"))
async def edit_layout_menu(callback: CallbackQuery, state: FSMContext):
    """Menu de edição de um layout específico."""
    layout_id = UUID(callback.data.split(":")[-1])
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        layout = await _get_layout_by_id(session, tenant.id, layout_id)
        if layout is None:
            await callback.answer("Layout não encontrado.")
            return

    await state.update_data(edit_layout_id=str(layout.id))

    # Parse buttons_json
    try:
        buttons_list = json.loads(layout.buttons_json or "[]")
    except json.JSONDecodeError:
        buttons_list = []

    text = (
        f"✏️ Editando layout <b>{layout.code}</b>\n"
        f"Row width: {layout.row_width}\n"
        f"Botões: {len(buttons_list)}\n\n"
        "Escolha uma ação:"
    )
    buttons = [
        [create_button("➕ Adicionar botão", "kbb:add_button")],
        [create_button("📝 Listar/Editar botão", "kbb:list_buttons")],
        [create_button("🗑 Remover botão", "kbb:remove_button_select")],
        [create_button("🔢 Alterar row_width", "kbb:change_row_width")],
        [create_button("Ativar/Desativar layout", "kbb:toggle_layout")],
        [create_button("🔙 VOLTAR", "kbb:select_layout_edit")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


# ----------------------------------------------------------------------
# ADICIONAR BOTÃO
# ----------------------------------------------------------------------

@router.callback_query(F.data == "kbb:add_button")
async def add_button_start(callback: CallbackQuery, state: FSMContext):
    """Inicia adição de botão ao layout."""
    await state.set_state(AdminButtonsStates.WAITING_BUTTON_TEXT)
    text = "Digite o texto do botão (pode incluir emoji):"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "admin:buttons")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminButtonsStates.WAITING_BUTTON_TEXT)
async def process_button_text(message: Message, state: FSMContext):
    """Recebe texto e pergunta se é callback ou URL."""
    button_text = message.text.strip()
    if not button_text:
        await message.answer("Texto vazio.")
        return

    await state.update_data(button_text=button_text)
    await state.set_state(AdminButtonsStates.WAITING_BUTTON_CALLBACK)
    text = "O botão será de callback ou URL? Digite:\n- callback: <seu_callback>\n- url: <sua_url>"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "admin:buttons")]]
    )
    await message.answer(text, reply_markup=keyboard)


@router.message(AdminButtonsStates.WAITING_BUTTON_CALLBACK)
async def process_button_callback(message: Message, state: FSMContext):
    """Recebe tipo e valor do botão."""
    raw = message.text.strip().lower()
    if raw.startswith("callback:"):
        callback_data = raw[len("callback:"):].strip()
        await state.update_data(button_callback=callback_data, button_url=None)
        await _finish_add_button(message, state)
    elif raw.startswith("url:"):
        url = raw[len("url:"):].strip()
        await state.update_data(button_url=url, button_callback=None)
        await _finish_add_button(message, state)
    else:
        await message.answer("Formato inválido. Digite 'callback: valor' ou 'url: valor'.")


async def _finish_add_button(message: Message, state: FSMContext):
    """Adiciona o botão ao layout atual."""
    data = await state.get_data()
    layout_id = UUID(data.get("edit_layout_id"))
    button_text = data.get("button_text")
    button_callback = data.get("button_callback")
    button_url = data.get("button_url")

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

        layout = await _get_layout_by_id(session, tenant.id, layout_id)
        if layout is None:
            await message.answer("Layout não encontrado.")
            await state.clear()
            return

        try:
            buttons_list = json.loads(layout.buttons_json or "[]")
        except json.JSONDecodeError:
            buttons_list = []

        new_button = {"text": button_text}
        if button_callback:
            new_button["callback"] = button_callback
        elif button_url:
            new_button["url"] = button_url
        else:
            await message.answer("Callback ou URL obrigatórios.")
            await state.clear()
            return

        buttons_list.append(new_button)
        layout.buttons_json = json.dumps(buttons_list, ensure_ascii=False)
        await session.commit()

    await state.clear()
    await message.answer("✅ Botão adicionado com sucesso!")


# ----------------------------------------------------------------------
# LISTAR/EDITAR BOTÃO
# ----------------------------------------------------------------------

@router.callback_query(F.data == "kbb:list_buttons")
async def list_buttons(callback: CallbackQuery, state: FSMContext):
    """Lista botões do layout para seleção."""
    data = await state.get_data()
    layout_id = UUID(data.get("edit_layout_id"))

    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        layout = await _get_layout_by_id(session, tenant.id, layout_id)
        if layout is None:
            await callback.answer("Layout não encontrado.")
            return

        try:
            buttons_list = json.loads(layout.buttons_json or "[]")
        except json.JSONDecodeError:
            buttons_list = []

    if not buttons_list:
        await callback.answer("Nenhum botão neste layout.")
        return

    text = f"Botões do layout <b>{layout.code}</b>:\n\n"
    for i, btn in enumerate(buttons_list, start=1):
        btn_text = btn.get("text", "")
        btn_type = "URL" if "url" in btn else "Callback"
        btn_value = btn.get("callback") or btn.get("url", "")
        text += f"{i}. {btn_text} ({btn_type}: {btn_value})\n"

    buttons = []
    for i, btn in enumerate(buttons_list):
        buttons.append([create_button(f"Editar {i+1}", f"kbb:edit_button_select:{i}")])
    buttons.append([create_button("🔙 VOLTAR", "kbb:edit_layout_menu")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data.startswith("kbb:edit_button_select:"))
async def edit_button_select(callback: CallbackQuery, state: FSMContext):
    """Pede novo texto para o botão selecionado."""
    index = int(callback.data.split(":")[-1])
    await state.update_data(edit_button_index=index)
    await state.set_state(AdminButtonsStates.WAITING_BUTTON_NEW_TEXT)
    text = "Digite o novo texto do botão:"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "kbb:list_buttons")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminButtonsStates.WAITING_BUTTON_NEW_TEXT)
async def process_new_button_text(message: Message, state: FSMContext):
    """Recebe novo texto e pede callback/url."""
    new_text = message.text.strip()
    if not new_text:
        await message.answer("Texto vazio.")
        return

    await state.update_data(new_button_text=new_text)
    await state.set_state(AdminButtonsStates.WAITING_BUTTON_NEW_CALLBACK)
    await message.answer("Digite o novo callback ou url (formato 'callback: valor' ou 'url: valor'):")


@router.message(AdminButtonsStates.WAITING_BUTTON_NEW_CALLBACK)
async def process_new_button_callback(message: Message, state: FSMContext):
    """Recebe callback/url e atualiza botão."""
    raw = message.text.strip().lower()
    callback_data = None
    url = None
    if raw.startswith("callback:"):
        callback_data = raw[len("callback:"):].strip()
    elif raw.startswith("url:"):
        url = raw[len("url:"):].strip()
    else:
        await message.answer("Formato inválido.")
        return

    data = await state.get_data()
    layout_id = UUID(data.get("edit_layout_id"))
    index = int(data.get("edit_button_index"))
    new_text = data.get("new_button_text")

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

        layout = await _get_layout_by_id(session, tenant.id, layout_id)
        if layout is None:
            await message.answer("Layout não encontrado.")
            await state.clear()
            return

        try:
            buttons_list = json.loads(layout.buttons_json or "[]")
        except json.JSONDecodeError:
            buttons_list = []

        if index >= len(buttons_list):
            await message.answer("Índice inválido.")
            await state.clear()
            return

        buttons_list[index]["text"] = new_text
        if callback_data:
            buttons_list[index].pop("url", None)
            buttons_list[index]["callback"] = callback_data
        elif url:
            buttons_list[index].pop("callback", None)
            buttons_list[index]["url"] = url

        layout.buttons_json = json.dumps(buttons_list, ensure_ascii=False)
        await session.commit()

    await state.clear()
    await message.answer("✅ Botão atualizado!")


# ----------------------------------------------------------------------
# REMOVER BOTÃO
# ----------------------------------------------------------------------

@router.callback_query(F.data == "kbb:remove_button_select")
async def remove_button_select(callback: CallbackQuery, state: FSMContext):
    """Lista botões para remoção."""
    data = await state.get_data()
    layout_id = UUID(data.get("edit_layout_id"))

    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        layout = await _get_layout_by_id(session, tenant.id, layout_id)
        if layout is None:
            await callback.answer("Layout não encontrado.")
            return

        try:
            buttons_list = json.loads(layout.buttons_json or "[]")
        except json.JSONDecodeError:
            buttons_list = []

    if not buttons_list:
        await callback.answer("Nenhum botão.")
        return

    text = "Selecione o botão para remover:"
    buttons = []
    for i, btn in enumerate(buttons_list):
        buttons.append([create_button(btn.get("text", f"Botão {i+1}"), f"kbb:remove_button:{i}")])
    buttons.append([create_button("🔙 VOLTAR", "kbb:edit_layout_menu")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data.startswith("kbb:remove_button:"))
async def remove_button(callback: CallbackQuery, state: FSMContext):
    """Remove botão selecionado."""
    index = int(callback.data.split(":")[-1])
    data = await state.get_data()
    layout_id = UUID(data.get("edit_layout_id"))

    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        layout = await _get_layout_by_id(session, tenant.id, layout_id)
        if layout is None:
            await callback.answer("Layout não encontrado.")
            return

        try:
            buttons_list = json.loads(layout.buttons_json or "[]")
        except json.JSONDecodeError:
            buttons_list = []

        if index < len(buttons_list):
            buttons_list.pop(index)
            layout.buttons_json = json.dumps(buttons_list, ensure_ascii=False)
            await session.commit()
            await callback.answer("Botão removido.")
        else:
            await callback.answer("Índice inválido.")

    await remove_button_select(callback, state)


# ----------------------------------------------------------------------
# ALTERAR ROW_WIDTH
# ----------------------------------------------------------------------

@router.callback_query(F.data == "kbb:change_row_width")
async def change_row_width_start(callback: CallbackQuery, state: FSMContext):
    """Pede novo row_width."""
    await state.set_state(AdminButtonsStates.WAITING_ROW_WIDTH)
    text = "Digite a nova quantidade de botões por linha (1-5):"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "kbb:edit_layout_menu")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminButtonsStates.WAITING_ROW_WIDTH)
async def process_row_width_change(message: Message, state: FSMContext):
    """Salva novo row_width."""
    try:
        row_width = int(message.text.strip())
        if row_width < 1 or row_width > 5:
            raise ValueError
    except ValueError:
        await message.answer("Valor inválido.")
        return

    data = await state.get_data()
    layout_id = UUID(data.get("edit_layout_id"))

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

        layout = await _get_layout_by_id(session, tenant.id, layout_id)
        if layout:
            layout.row_width = row_width
            await session.commit()
            await message.answer("✅ Row width atualizado.")
        else:
            await message.answer("Layout não encontrado.")

    await state.clear()


# ----------------------------------------------------------------------
# TOGGLE LAYOUT
# ----------------------------------------------------------------------

@router.callback_query(F.data == "kbb:toggle_layout")
async def toggle_layout(callback: CallbackQuery, state: FSMContext):
    """Ativa/desativa layout."""
    data = await state.get_data()
    layout_id = UUID(data.get("edit_layout_id"))

    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        layout = await _get_layout_by_id(session, tenant.id, layout_id)
        if layout:
            layout.is_active = not layout.is_active
            await session.commit()
            await callback.answer(f"Layout {'ativado' if layout.is_active else 'desativado'}.")
        else:
            await callback.answer("Layout não encontrado.")

    await edit_layout_menu(callback, state)


# ----------------------------------------------------------------------
# EXCLUIR LAYOUT
# ----------------------------------------------------------------------

@router.callback_query(F.data == "kbb:select_layout_delete")
async def select_layout_delete(callback: CallbackQuery, state: FSMContext):
    """Lista layouts para exclusão."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return
        layouts = await _get_layouts(session, tenant.id)

    if not layouts:
        await callback.answer("Nenhum layout cadastrado.")
        return

    text = "Selecione o layout para excluir:"
    buttons = []
    for layout in layouts:
        buttons.append([create_button(layout.code, f"kbb:delete_layout:{layout.id}")])
    buttons.append([create_button("🔙 VOLTAR", "admin:buttons")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data.startswith("kbb:delete_layout:"))
async def delete_layout(callback: CallbackQuery, state: FSMContext):
    """Exclui layout (soft delete)."""
    layout_id = UUID(callback.data.split(":")[-1])
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        layout = await _get_layout_by_id(session, tenant.id, layout_id)
        if layout:
            layout.soft_delete()
            await session.commit()
            await callback.answer("Layout excluído.")
        else:
            await callback.answer("Layout não encontrado.")

    await show_buttons_menu(callback, state)


# ----------------------------------------------------------------------
# SELEÇÃO PARA TOGGLE
# ----------------------------------------------------------------------

@router.callback_query(F.data == "kbb:select_layout_toggle")
async def select_layout_toggle(callback: CallbackQuery, state: FSMContext):
    """Lista layouts para ativar/desativar."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return
        layouts = await _get_layouts(session, tenant.id)

    if not layouts:
        await callback.answer("Nenhum layout cadastrado.")
        return

    text = "Selecione o layout para alternar:"
    buttons = []
    for layout in layouts:
        status = "🟢" if layout.is_active else "🔴"
        buttons.append([create_button(f"{status} {layout.code}", f"kbb:toggle_layout_external:{layout.id}")])
    buttons.append([create_button("🔙 VOLTAR", "admin:buttons")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data.startswith("kbb:toggle_layout_external:"))
async def toggle_layout_external(callback: CallbackQuery, state: FSMContext):
    """Alterna status do layout selecionado."""
    layout_id = UUID(callback.data.split(":")[-1])
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        layout = await _get_layout_by_id(session, tenant.id, layout_id)
        if layout:
            layout.is_active = not layout.is_active
            await session.commit()
            await callback.answer(f"Layout {'ativado' if layout.is_active else 'desativado'}.")
        else:
            await callback.answer("Layout não encontrado.")

    await select_layout_toggle(callback, state)
