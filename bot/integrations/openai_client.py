"""
Integração com OpenAI (IA).

Fornece funções reais para:
- Enviar prompts e receber respostas da IA
- Controlar temperatura e máximo de tokens

Usa httpx para chamadas assíncronas à API da OpenAI.
"""

import logging
from typing import Optional, List, Dict, Any

import httpx

from bot.core.config import settings

logger = logging.getLogger(__name__)

OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"


class OpenAIError(Exception):
    """Erro ao interagir com a API da OpenAI."""
    pass


class OpenAIClient:
    """
    Cliente para a API da OpenAI (Chat Completions).
    """

    def __init__(self):
        self.api_key = settings.OPENAI_API_KEY.get_secret_value() if settings.OPENAI_API_KEY else None
        self.model = settings.OPENAI_MODEL or "gpt-4o-mini"

        if not self.api_key:
            logger.warning("OpenAI API key não configurada. IA indisponível.")

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> Optional[str]:
        """
        Envia uma conversa para a IA e retorna a resposta.

        Args:
            messages: Lista de mensagens no formato [{"role": "system"|"user"|"assistant", "content": "..."}]
            temperature: Temperatura da resposta (0 a 1).
            max_tokens: Limite de tokens (opcional).

        Returns:
            Optional[str]: Texto da resposta, ou None se falhar.
        """
        if not self.api_key:
            logger.error("OpenAI API key não configurada.")
            return None

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(OPENAI_API_URL, headers=headers, json=payload)
                if resp.status_code >= 400:
                    logger.error(f"OpenAI error {resp.status_code}: {resp.text}")
                    return None

                data = resp.json()
                choices = data.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "")
                return None
        except httpx.HTTPError as e:
            logger.exception(f"Erro de comunicação com OpenAI: {e}")
            return None
