"""
Script para criação de usuário administrador/dono.

Uso:
    python -m scripts.create_admin <tenant_slug> <telegram_id> [--owner] [--admin]

Exemplo:
    python -m scripts.create_admin larizinha 6995978182 --owner

Cria um usuário vinculado ao tenant e o promove a admin/dono.
"""

import asyncio
import sys
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select

from bot.core.database import get_async_session_factory
from bot.models.tenant import Tenant
from bot.models.user import User
from bot.models.admin_user import AdminUser


async def create_admin(
    tenant_slug: str,
    telegram_id: int,
    is_owner: bool = False,
    is_admin: bool = False,
) -> User:
    """
    Cria ou atualiza usuário como admin/dono do tenant.

    Args:
        tenant_slug: Slug do tenant.
        telegram_id: ID do Telegram do usuário.
        is_owner: Se deve ser dono.
        is_admin: Se deve ser administrador.

    Returns:
        User: Usuário criado/atualizado.
    """
    async with get_async_session_factory() as session:
        # Obtém tenant pelo slug
        tenant = (await session.execute(
            select(Tenant).where(Tenant.slug == tenant_slug, Tenant.deleted_at.is_(None))
        )).scalar_one_or_none()
        if tenant is None:
            raise ValueError(f"Tenant com slug '{tenant_slug}' não encontrado.")

        # Busca usuário existente
        user = (await session.execute(
            select(User).where(
                User.tenant_id == tenant.id,
                User.telegram_id == telegram_id,
                User.deleted_at.is_(None),
            )
        )).scalar_one_or_none()

        if user is None:
            # Cria novo usuário
            user = User(
                tenant_id=tenant.id,
                telegram_id=telegram_id,
                registered_at=datetime.now(timezone.utc),
                is_blocked=False,
                is_owner=is_owner,
                is_admin=is_admin,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            print(f"✅ Usuário criado com sucesso. ID: {user.id}")
        else:
            # Atualiza papéis
            if is_owner:
                user.is_owner = True
            if is_admin:
                user.is_admin = True
            await session.commit()
            await session.refresh(user)
            print(f"✅ Usuário existente atualizado. ID: {user.id}")

        # Se for admin ou owner, garante registro em AdminUser também
        if (is_owner or is_admin) and not user.is_owner and not user.is_admin:
            existing_admin = (await session.execute(
                select(AdminUser).where(
                    AdminUser.tenant_id == tenant.id,
                    AdminUser.user_id == user.id,
                    AdminUser.is_active == True,
                )
            )).scalar_one_or_none()
            if not existing_admin:
                new_admin = AdminUser(
                    tenant_id=tenant.id,
                    user_id=user.id,
                    role="ADMIN" if is_admin else "OWNER",
                    is_active=True,
                    granted_at=datetime.now(timezone.utc),
                )
                session.add(new_admin)
                await session.commit()
                print("✅ Registro em AdminUser criado.")

        return user


def main():
    """Executa o script."""
    if len(sys.argv) < 3:
        print("Uso: python -m scripts.create_admin <tenant_slug> <telegram_id> [--owner] [--admin]")
        sys.exit(1)

    tenant_slug = sys.argv[1]
    try:
        telegram_id = int(sys.argv[2])
    except ValueError:
        print("telegram_id deve ser um número inteiro.")
        sys.exit(1)

    is_owner = "--owner" in sys.argv
    is_admin = "--admin" in sys.argv

    if not is_owner and not is_admin:
        print("É necessário informar --owner ou --admin.")
        sys.exit(1)

    asyncio.run(create_admin(tenant_slug, telegram_id, is_owner, is_admin))


if __name__ == "__main__":
    main()
