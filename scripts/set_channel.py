"""
Script para configurar canal de compras/estoque.

Uso:
    python -m scripts.set_channel <tenant_slug> <channel_id>

Exemplo:
    python -m scripts.set_channel larizinha -1001234567890

Salva o ID do canal na tabela Settings com chave 'purchase_channel_id'.
"""

import asyncio
import sys

from sqlalchemy import select

from bot.core.database import get_async_session_factory
from bot.models.tenant import Tenant
from bot.models.settings import Settings


async def set_channel(tenant_slug: str, channel_id: str) -> None:
    """
    Define o canal de notificações de compras para o tenant.

    Args:
        tenant_slug: Slug do tenant.
        channel_id: ID do canal (ex: -100...).
    """
    async with get_async_session_factory() as session:
        tenant = (await session.execute(
            select(Tenant).where(Tenant.slug == tenant_slug, Tenant.deleted_at.is_(None))
        )).scalar_one_or_none()
        if tenant is None:
            raise ValueError(f"Tenant com slug '{tenant_slug}' não encontrado.")

        setting = (await session.execute(
            select(Settings).where(
                Settings.tenant_id == tenant.id,
                Settings.key == "purchase_channel_id",
                Settings.deleted_at.is_(None),
            )
        )).scalar_one_or_none()

        if setting:
            setting.value = channel_id
        else:
            setting = Settings(
                tenant_id=tenant.id,
                key="purchase_channel_id",
                value=channel_id,
            )
            session.add(setting)

        await session.commit()
        print(f"✅ Canal de compras configurado para tenant '{tenant_slug}': {channel_id}")


def main():
    if len(sys.argv) != 3:
        print("Uso: python -m scripts.set_channel <tenant_slug> <channel_id>")
        sys.exit(1)

    tenant_slug = sys.argv[1]
    channel_id = sys.argv[2]

    asyncio.run(set_channel(tenant_slug, channel_id))


if __name__ == "__main__":
    main()
