"""
Módulo de segurança e criptografia.

Fornece funções para:
- Hash e verificação de senhas (bcrypt)
- Criptografia simétrica de dados sensíveis (Fernet)
- Geração de tokens/URLs seguras (secrets)
- Mascaramento de informações (e-mail, telefone, etc.)
"""

import base64
import hashlib
import secrets
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from passlib.context import CryptContext

from bot.core.config import settings

# Contexto de hash de senha (bcrypt)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Chave de criptografia derivada da ENCRYPTION_KEY (32 bytes url-safe base64)
_fernet_key = base64.urlsafe_b64encode(
    hashlib.sha256(settings.ENCRYPTION_KEY.get_secret_value().encode("utf-8")).digest()
)
_fernet = Fernet(_fernet_key)


def hash_password(password: str) -> str:
    """
    Gera hash seguro de senha usando bcrypt.

    Args:
        password: Senha em texto puro.

    Returns:
        str: Hash da senha.
    """
    return pwd_context.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    """
    Verifica se a senha corresponde ao hash.

    Args:
        password: Senha em texto puro.
        hashed_password: Hash armazenado.

    Returns:
        bool: True se corresponder, False caso contrário.
    """
    try:
        return pwd_context.verify(password, hashed_password)
    except Exception:
        return False


def encrypt_data(data: str) -> str:
    """
    Criptografa dados sensíveis (ex.: logins, tokens, chaves Pix).

    Args:
        data: Texto puro a ser criptografado.

    Returns:
        str: Dado criptografado em base64 (token Fernet).
    """
    if not data:
        return ""
    return _fernet.encrypt(data.encode("utf-8")).decode("utf-8")


def decrypt_data(encrypted_data: str) -> str:
    """
    Descriptografa dados previamente criptografados.

    Args:
        encrypted_data: Token Fernet em base64.

    Returns:
        str: Texto puro original, ou string vazia se falhar.
    """
    if not encrypted_data:
        return ""
    try:
        return _fernet.decrypt(encrypted_data.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        # Logar? (evitar vazamento de informação em produção)
        return ""


def generate_secure_token(length: int = 32) -> str:
    """
    Gera um token aleatório seguro (URL-safe) usando `secrets`.

    Args:
        length: Número de bytes do token (padrão 32 -> 43 caracteres).

    Returns:
        str: Token seguro.
    """
    return secrets.token_urlsafe(length)


def generate_short_code(length: int = 6) -> str:
    """
    Gera um código curto numérico (ex.: código de verificação).

    Args:
        length: Quantidade de dígitos.

    Returns:
        str: Código numérico.
    """
    return "".join(str(secrets.randbelow(10)) for _ in range(length))


def mask_email(email: str) -> str:
    """
    Mascara um endereço de e-mail, exibindo apenas iniciais e domínio.

    Exemplo: joao.silva@gmail.com -> j***a@gmail.com

    Args:
        email: E-mail completo.

    Returns:
        str: E-mail mascarado.
    """
    if "@" not in email:
        return email
    local, domain = email.rsplit("@", 1)
    if len(local) <= 2:
        masked_local = local[0] + "*"
    else:
        masked_local = local[0] + "*" * (len(local) - 2) + local[-1]
    return f"{masked_local}@{domain}"


def mask_phone(phone: str) -> str:
    """
    Mascara um número de telefone, mantendo apenas os primeiros e últimos dígitos.

    Exemplo: 11999998888 -> 119****8888

    Args:
        phone: Número de telefone (somente dígitos).

    Returns:
        str: Telefone mascarado.
    """
    if len(phone) <= 4:
        return "*" * len(phone)
    return phone[:3] + "*" * (len(phone) - 6) + phone[-3:]


def mask_card_number(card_number: str) -> str:
    """
    Mascara um número de cartão, exibindo apenas os 4 últimos dígitos.

    Exemplo: 4111111111111111 -> **** **** **** 1111

    Args:
        card_number: Número do cartão.

    Returns:
        str: Cartão mascarado.
    """
    if len(card_number) < 4:
        return "****"
    return "**** **** **** " + card_number[-4:]


def constant_time_compare(a: str, b: str) -> bool:
    """
    Comparação em tempo constante para evitar timing attacks.

    Args:
        a: Primeira string.
        b: Segunda string.

    Returns:
        bool: True se forem iguais.
    """
    return secrets.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
