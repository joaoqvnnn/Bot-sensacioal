"""
Integração de envio de e-mails via SMTP.

Usa aiosmtplib para envio assíncrono. Suporta texto simples, HTML e anexos.
As credenciais vêm das configurações (nunca hardcoded).
"""

import logging
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Optional

import aiosmtplib

from bot.core.config import settings

logger = logging.getLogger(__name__)


class EmailSender:
    """
    Cliente para envio de e-mails usando SMTP.
    """

    def __init__(self):
        self.host = settings.SMTP_HOST
        self.port = settings.SMTP_PORT
        self.username = settings.SMTP_USER
        self.password = settings.SMTP_PASSWORD.get_secret_value() if settings.SMTP_PASSWORD else None
        self.from_address = settings.SMTP_FROM
        self.use_tls = settings.SMTP_TLS

        if not self.host or not self.from_address:
            logger.warning("SMTP não configurado. Envio de e-mail indisponível.")

    async def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        html: bool = False,
        attachments: Optional[List[str]] = None,
    ) -> bool:
        """
        Envia um e-mail.

        Args:
            to: Endereço do destinatário.
            subject: Assunto.
            body: Corpo da mensagem (texto ou HTML).
            html: Se True, interpreta body como HTML.
            attachments: Lista de caminhos de arquivos para anexar.

        Returns:
            bool: True se enviado com sucesso, False caso contrário.
        """
        if not self.host or not self.from_address:
            logger.error("SMTP não configurado. Não é possível enviar e-mail.")
            return False

        try:
            message = MIMEMultipart()
            message["From"] = self.from_address
            message["To"] = to
            message["Subject"] = subject

            # Corpo
            content_type = "html" if html else "plain"
            message.attach(MIMEText(body, content_type, "utf-8"))

            # Anexos
            if attachments:
                for file_path in attachments:
                    with open(file_path, "rb") as f:
                        part = MIMEApplication(f.read(), Name=file_path.split("/")[-1])
                        part["Content-Disposition"] = f'attachment; filename="{file_path.split("/")[-1]}"'
                        message.attach(part)

            # Envia via SMTP
            await aiosmtplib.send(
                message,
                hostname=self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                start_tls=self.use_tls,
            )
            logger.info(f"E-mail enviado para {to} com assunto '{subject}'")
            return True
        except Exception as e:
            logger.exception(f"Falha ao enviar e-mail para {to}: {e}")
            return False
