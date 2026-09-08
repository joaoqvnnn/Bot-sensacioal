"""
Script para criação de tenant inicial.

Uso:
    python -m scripts.create_tenant <nome> <slug> [--plan <plano>] [--vip] [--dias <dias>]

Exemplo:
    python -m scripts.create_tenant "Larizinha Store" larizinha --plan "gold" --vip --dias 365

Cria um tenant ativo no banco de dados.
"""

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

from bot.core.database import get_async_session_factory
from bot.models.tenant import Tenant
from bot.core.config import settings


async def create_tenant(
    name: str,
    slug: str,
    plan: Optional[str] = None,
    vip: bool = False,
    expires_days: int = 365,
) -> Tenant:
    """
    Cria um novo tenant.

    Args:
        name: Nome do tenant.
        slug: Slug único.
        plan: Plano (opcional).
        vip: Se é VIP.
        expires_days: Dias até vencimento.

    Returns:
        Tenant: Tenant criado.

    Raises:
        ValueError: Se o slug já existir.
    """
    async with get_async_session_factory() as session:
        # Verifica duplicidade de slug
        from sqlalchemy import select
        existing = (await session.execute(
            select(Tenant).where(Tenant.slug == slug, Tenant.deleted_at.is_(None))
        )).scalar_one_or_none()
        if existing:
            raise ValueError(f"Slug '{slug}' já existe.")

        expires_at = datetime.now(timezone.utc) + timedelta(days=expires_days) if expires_days > 0 else None

        tenant = Tenant(
            name=name,
            slug=slug,
            plan=plan,
            vip=vip,
            is_active=True,
            expires_at=expires_at,
        )
        session.add(tenant)
        await session.commit()
        await session.refresh(tenant)
        print(f"✅ Tenant '{name}' criado com sucesso. ID: {tenant.id}")
        return tenant


def main():
    """Executa o script."""
    if len(sys.argv) < 3:
        print("Uso: python -m scripts.create_tenant <nome> <slug> [--plan <plano>] [--vip] [--dias <dias>]")
        sys.exit(1)

    name = sys.argv[1]
    slug = sys.argv[2]
    plan = None
    vip = False
    dias = 365

    if "--plan" in sys.argv:
        idx = sys.argv.index("--plan")
        if idx + 1 < len(sys.argv):
            plan = sys.argv[idx + 1]
    if "--vip" in sys.argv:
        vip = True
    if "--dias" in sys.argv:
        idx = sys.argv.index("--dias")
        if idx + 1 < len(sys.argv):
            try:
                dias = int(sys.argv[idx + 1])
            except ValueError:
                print("--dias deve ser um número inteiro.")
                sys.exit(1)

    asyncio.run(create_tenant(name, slug, plan, vip, dias))


if __name__ == "__main__":
    main()
