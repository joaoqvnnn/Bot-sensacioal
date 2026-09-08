"""
Integração com Mercado Pago (API Pix).

Fornece funções reais para:
- Criar cobrança Pix (QR Code e copia-e-cola)
- Consultar status de pagamento
- Processar notificação de webhook

Usa httpx para chamadas assíncronas à API oficial.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import httpx

from bot.core.config import settings

logger = logging.getLogger(__name__)

MERCADO_PAGO_API_URL = "https://api.mercadopago.com"


class MercadoPagoError(Exception):
    """Erro ao interagir com a API do Mercado Pago."""
    pass


class MercadoPagoClient:
    """
    Cliente para API do Mercado Pago.
    """

    def __init__(self, access_token: Optional[str] = None):
        """
        Inicializa o cliente com token de acesso.

        Args:
            access_token: Token de acesso (opcional; usa settings se None).
        """
        self.access_token = access_token or (
            settings.MERCADO_PAGO_ACCESS_TOKEN.get_secret_value()
            if settings.MERCADO_PAGO_ACCESS_TOKEN
            else None
        )
        if not self.access_token:
            raise MercadoPagoError("Token de acesso do Mercado Pago não configurado.")

        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    async def _request(self, method: str, endpoint: str, data: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Faz requisição HTTP à API do Mercado Pago.

        Args:
            method: Método HTTP (GET, POST, PUT).
            endpoint: Caminho do endpoint.
            data: Dados JSON para envio (opcional).

        Returns:
            dict: Resposta JSON.

        Raises:
            MercadoPagoError: Se a API retornar erro.
        """
        url = f"{MERCADO_PAGO_API_URL}{endpoint}"
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                if method.upper() == "GET":
                    resp = await client.get(url, headers=self.headers)
                elif method.upper() == "POST":
                    resp = await client.post(url, headers=self.headers, json=data)
                elif method.upper() == "PUT":
                    resp = await client.put(url, headers=self.headers, json=data)
                else:
                    raise MercadoPagoError(f"Método HTTP não suportado: {method}")

                if resp.status_code >= 400:
                    logger.error(f"Mercado Pago error {resp.status_code}: {resp.text}")
                    raise MercadoPagoError(f"Erro {resp.status_code} da API Mercado Pago")

                return resp.json()
            except httpx.HTTPError as e:
                logger.exception(f"Erro de conexão com Mercado Pago: {e}")
                raise MercadoPagoError(f"Falha de comunicação: {e}")

    async def create_pix_payment(
        self,
        amount_cents: int,
        description: str = "Recarga",
        expiration_minutes: int = 10,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Cria uma cobrança Pix.

        Args:
            amount_cents: Valor em centavos.
            description: Descrição da cobrança.
            expiration_minutes: Minutos para expiração.
            idempotency_key: Chave de idempotência (opcional).

        Returns:
            dict: Dados da cobrança (id, qr_code, qr_code_base64, copia_e_cola).
        """
        # Converte centavos para decimal (ex: 800 -> 8.00)
        amount = amount_cents / 100

        payload = {
            "transaction_amount": amount,
            "description": description,
            "payment_method_id": "pix",
            "date_of_expiration": (
                datetime.now(timezone.utc) + timedelta(minutes=expiration_minutes)
            ).isoformat(),
        }
        if idempotency_key:
            payload["external_reference"] = idempotency_key

        data = await self._request("POST", "/v1/payments", payload)

        # A API retorna "point_of_interaction" com QR code e copia-e-cola
        qr_code_url = None
        qr_code_base64 = None
        copia_e_cola = None
        poi = data.get("point_of_interaction", {}).get("transaction_data", {})
        if poi:
            qr_code_url = poi.get("qr_code")
            qr_code_base64 = poi.get("qr_code_base64")
            copia_e_cola = poi.get("qr_code")

        return {
            "external_payment_id": data.get("id"),
            "qr_code_url": qr_code_url,
            "qr_code_base64": qr_code_base64,
            "pix_code": copia_e_cola,
            "status": data.get("status"),
        }

    async def get_payment_status(self, payment_id: str) -> str:
        """
        Consulta o status de um pagamento.

        Args:
            payment_id: ID externo do pagamento.

        Returns:
            str: Status (approved, pending, etc.).
        """
        data = await self._request("GET", f"/v1/payments/{payment_id}")
        return data.get("status", "unknown")

    async def cancel_payment(self, payment_id: str) -> bool:
        """
        Cancela um pagamento pendente.

        Args:
            payment_id: ID externo do pagamento.

        Returns:
            bool: True se cancelado com sucesso.
        """
        try:
            await self._request("PUT", f"/v1/payments/{payment_id}", {"status": "cancelled"})
            return True
        except MercadoPagoError:
            return False
