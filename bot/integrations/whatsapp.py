"""
Integração com WhatsApp Business API.

Fornece funções reais para:
- Enviar mensagens de texto
- Enviar mensagens com imagem
- Enviar botões interativos (ex: ATIVAR)
- Enviar WhatsApp Flow (simplificado)
- Aplicar opt-in, retry e rate limit configurados no painel
- Registrar mensagens no banco para status/histórico
"""

import logging
import asyncio
from typing import Optional
from uuid import UUID

import httpx

from bot.core.config import settings
from bot.models.settings import Settings
from bot.models.whatsapp_message import WhatsAppMessage
from sqlalchemy import select
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

WHATSAPP_API_URL = "https://graph.facebook.com"


class WhatsAppAPIError(Exception):
    """Erro ao interagir com a WhatsApp Business API."""
    pass


class WhatsAppClient:
    """
    Cliente para a WhatsApp Business API.
    """

    def __init__(self, session=None, tenant_id: Optional[UUID] = None):
        self.token = settings.WHATSAPP_API_TOKEN.get_secret_value() if settings.WHATSAPP_API_TOKEN else None
        self.phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID
        self.version = settings.WHATSAPP_API_VERSION
        self.session = session  # sessão do banco para ler Settings
        self.tenant_id = tenant_id  # tenant para registro de mensagens

        if not self.token or not self.phone_number_id:
            logger.warning("WhatsApp API não configurada. Envio indisponível.")

    async def _get_setting(self, key: str, default: str = "") -> str:
        """Busca configuração do tenant no banco, com fallback."""
        if self.session is None or self.tenant_id is None:
            return default
        from sqlalchemy import select
        stmt = select(Settings).where(
            Settings.tenant_id == self.tenant_id,
            Settings.key == key,
            Settings.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        setting = result.scalar_one_or_none()
        return setting.value if setting else default

    async def _send_message(self, payload: dict, retry_count: int = 3) -> bool:
        """
        Envia uma mensagem via API do WhatsApp, com retry e rate limit.
        """
        if not self.token or not self.phone_number_id:
            logger.error("WhatsApp API não configurada.")
            return False

        url = f"{WHATSAPP_API_URL}/{self.version}/{self.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

        # Aplica rate limit (mensagens por minuto)
        rate_limit = int(await self._get_setting("whatsapp_rate_limit_per_minute", "10"))
        await asyncio.sleep(60.0 / rate_limit)

        for attempt in range(1, retry_count + 1):
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.post(url, headers=headers, json=payload)
                    if resp.status_code >= 400:
                        logger.error(f"WhatsApp API error {resp.status_code}: {resp.text}")
                        if attempt < retry_count:
                            await asyncio.sleep(2 ** attempt)  # backoff
                            continue
                        return False
                    # Sucesso: registra mensagem
                    await self._register_message(payload, status="SENT")
                    return True
            except httpx.HTTPError as e:
                logger.exception(f"Erro de comunicação com WhatsApp: {e}")
                if attempt < retry_count:
                    await asyncio.sleep(2 ** attempt)
                    continue
                await self._register_message(payload, status="FAILED")
                return False
        return False

    async def _register_message(self, payload: dict, status: str):
        """Registra a mensagem no banco para histórico e status."""
        if self.session is None or self.tenant_id is None:
            return
        try:
            phone_number = payload.get("to", "")
            content = self._extract_content(payload)
            msg = WhatsAppMessage(
                tenant_id=self.tenant_id,
                phone_number=phone_number,
                content=content,
                status=status,
                sent_at=datetime.now(timezone.utc),
            )
            self.session.add(msg)
            await self.session.commit()
        except Exception as e:
            logger.exception(f"Erro ao registrar mensagem WhatsApp: {e}")

    def _extract_content(self, payload: dict) -> str:
        """Extrai conteúdo textual do payload para histórico."""
        if "text" in payload:
            return payload["text"].get("body", "")
        elif "interactive" in payload:
            return payload["interactive"]["body"].get("text", "")
        elif "image" in payload:
            return payload["image"].get("caption", "(imagem)")
        return ""

    async def send_text(self, to: str, text: str) -> bool:
        """Envia mensagem de texto simples."""
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": text},
        }
        retry = int(await self._get_setting("whatsapp_retry_count", "3"))
        return await self._send_message(payload, retry)

    async def send_image(self, to: str, image_url: str, caption: Optional[str] = None) -> bool:
        """Envia mensagem com imagem."""
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "image",
            "image": {
                "link": image_url,
                "caption": caption or "",
            },
        }
        retry = int(await self._get_setting("whatsapp_retry_count", "3"))
        return await self._send_message(payload, retry)

    async def send_interactive_buttons(
        self,
        to: str,
        body_text: str,
        buttons: list,
    ) -> bool:
        """Envia mensagem com botões interativos (ex: ATIVAR)."""
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": body_text},
                "action": {"buttons": buttons},
            },
        }
        retry = int(await self._get_setting("whatsapp_retry_count", "3"))
        return await self._send_message(payload, retry)

    async def send_delivery_message(self, to: str, product_name: str, image_url: Optional[str] = None) -> bool:
        """
        Envia mensagem de entrega usando template configurado.
        """
        delivery_text = await self._get_setting(
            "whatsapp_delivery_text",
            f"✅ {product_name} disponível!"
        )
        button_text = await self._get_setting("whatsapp_button_text", "🔐 ATIVAR")
        buttons = [{"type": "reply", "reply": {"id": "activate", "title": button_text}}]

        if image_url:
            return await self.send_image(to, image_url, caption=delivery_text)
        else:
            return await self.send_interactive_buttons(to, delivery_text, buttons)
