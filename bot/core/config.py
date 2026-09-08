from functools import lru_cache
from typing import List, Optional

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configurações gerais do sistema, carregadas do ambiente."""

    # ==================================================================
    # METADADOS DA APLICAÇÃO
    # ==================================================================
    APP_NAME: str = "LarizinhaStore"
    APP_ENV: str = "development"
    APP_DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    TIMEZONE: str = "America/Sao_Paulo"

    # ==================================================================
    # TELEGRAM
    # ==================================================================
    TELEGRAM_BOT_TOKEN: SecretStr
    TELEGRAM_BOT_USERNAME: str
    TELEGRAM_ADMIN_IDS: List[int] = []
    TELEGRAM_OWNER_ID: int
    TELEGRAM_WEBHOOK_URL: Optional[AnyHttpUrl] = None
    TELEGRAM_WEBHOOK_SECRET: Optional[SecretStr] = None

    # ==================================================================
    # POSTGRESQL
    # ==================================================================
    POSTGRES_DB: str
    POSTGRES_USER: str
    POSTGRES_PASSWORD: SecretStr
    POSTGRES_HOST: str = "postgres"
    POSTGRES_PORT: int = 5432
    POSTGRES_ECHO: bool = False
    POSTGRES_POOL_SIZE: int = 10
    POSTGRES_MAX_OVERFLOW: int = 20
    POSTGRES_SSL: bool = False

    # ==================================================================
    # REDIS
    # ==================================================================
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: Optional[SecretStr] = None  # <- alterado para opcional
    REDIS_DB: int = 0

    # ==================================================================
    # MERCADO PAGO (PIX)
    # ==================================================================
    MERCADO_PAGO_ACCESS_TOKEN: Optional[SecretStr] = None
    MERCADO_PAGO_PUBLIC_KEY: Optional[str] = None
    MERCADO_PAGO_WEBHOOK_SECRET: Optional[SecretStr] = None
    MERCADO_PAGO_NOTIFICATION_URL: Optional[AnyHttpUrl] = None
    MERCADO_PAGO_EXPIRATION_MINUTES: int = 10
    MERCADO_PAGO_MIN_DEPOSIT: float = 1.00
    MERCADO_PAGO_MAX_DEPOSIT: float = 150.00

    # ==================================================================
    # WHATSAPP BUSINESS API
    # ==================================================================
    WHATSAPP_API_TOKEN: Optional[SecretStr] = None
    WHATSAPP_PHONE_NUMBER_ID: Optional[str] = None
    WHATSAPP_BUSINESS_ACCOUNT_ID: Optional[str] = None
    WHATSAPP_WEBHOOK_VERIFY_TOKEN: Optional[SecretStr] = None
    WHATSAPP_API_VERSION: str = "v18.0"
    WHATSAPP_ENABLED: bool = False

    # ==================================================================
    # OPENAI / IA
    # ==================================================================
    OPENAI_API_KEY: Optional[SecretStr] = None
    OPENAI_MODEL: str = "gpt-4o-mini"
    AI_ENABLED: bool = False

    # ==================================================================
    # E-MAIL (SMTP)
    # ==================================================================
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[SecretStr] = None
    SMTP_FROM: Optional[str] = None
    SMTP_TLS: bool = True

    # ==================================================================
    # WEBSITE / MINI APP
    # ==================================================================
    BASE_URL: Optional[AnyHttpUrl] = None
    FRONTEND_URL: Optional[AnyHttpUrl] = None
    MINI_APP_URL: Optional[AnyHttpUrl] = None

    # ==================================================================
    # SEGURANÇA / CRIPTOGRAFIA
    # ==================================================================
    SECRET_KEY: SecretStr
    ENCRYPTION_KEY: SecretStr
    HASH_ITERATIONS: int = 100000

    # ==================================================================
    # OUTROS
    # ==================================================================
    SUPPORT_CHAT_LINK: Optional[AnyHttpUrl] = None
    DEFAULT_GIFT_BONUS: float = 0.0
    ALLOW_USER_REGISTRATION: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        validate_default=True,
    )

    # ==================================================================
    # VALIDADORES
    # ==================================================================
    @field_validator("TELEGRAM_ADMIN_IDS", mode="before")
    @classmethod
    def parse_admin_ids(cls, v):
        if isinstance(v, list):
            return v
        if isinstance(v, int):
            return [v]
        if isinstance(v, str):
            if not v.strip():
                return []
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return v

    @field_validator("APP_ENV")
    @classmethod
    def validate_env(cls, v):
        if v not in ("development", "production"):
            raise ValueError("APP_ENV deve ser 'development' ou 'production'")
        return v

    @model_validator(mode="after")
    def validate_production(self):
        if self.APP_ENV == "production":
            if self.APP_DEBUG:
                raise ValueError("APP_DEBUG deve ser False em produção")
            if self.SMTP_TLS is False:
                raise ValueError("SMTP_TLS deve ser True em produção")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


# Instância global para uso em todo o código
settings = get_settings()
