"""
Integração de envio de e-mails via SMTP.

Usa aiosmtplib para envio assíncrono. Suporta texto simples, HTML e anexos.
Lê templates configurados no painel (Settings) quando disponíveis.
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

    def __init__(self, session=None, tenant_id=None):
        self.host = settings.SMTP_HOST
        self.port = settings.SMTP_PORT
        self.username = settings.SMTP_USER
        self.password = settings.SMTP_PASSWORD.get_secret_value() if settings.SMTP_PASSWORD else None
        self.from_address = settings.SMTP_FROM
        self.use_tls = settings.SMTP_TLS
        self.session = session
        self.tenant_id = tenant_id

        if not self.host or not self.from_address:
            logger.warning("SMTP não configurado. Envio de e-mail indisponível.")

    async def _get_setting(self, key: str, default: str = "") -> str:
        if self.session is None or self.tenant_id is None:
            return default
        from sqlalchemy import select
        from bot.models.settings import Settings
        stmt = select(Settings).where(
            Settings.tenant_id == self.tenant_id,
            Settings.key == key,
            Settings.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        setting = result.scalar_one_or_none()
        return setting.value if setting else default

    async def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        html: bool = False,
        attachments: Optional[List[str]] = None,
        template_code: Optional[str] = None,
    ) -> bool:
        """
        Envia um e-mail.

        Se template_code for fornecido, tenta buscar assunto e corpo configurados
        no painel (Settings) e ignora os parâmetros subject/body.
        """
        if not self.host or not self.from_address:
            logger.error("SMTP não configurado. Não é possível enviar e-mail.")
            return False

        # Se houver template configurado
        if template_code and self.session and self.tenant_id:
            template_subject = await self._get_setting(f"email_template_{template_code}_subject", "")
            template_body = await self._get_setting(f"email_template_{template_code}_body", "")
            if template_subject:
                subject = template_subject
            if template_body:
                body = template_body

        try:
            message = MIMEMultipart()
            message["From"] = self.from_address
            message["To"] = to
            message["Subject"] = subject

            content_type = "html" if html else "plain"
            message.attach(MIMEText(body, content_type, "utf-8"))

            if attachments:
                for file_path in attachments:
                    with open(file_path, "rb") as f:
                        part = MIMEApplication(f.read(), Name=file_path.split("/")[-1])
                        part["Content-Disposition"] = f'attachment; filename="{file_path.split("/")[-1]}"'
                        message.attach(part)

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
