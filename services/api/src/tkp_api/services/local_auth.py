"""本地账号认证服务。"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt

from tkp_api.core.config import get_settings
from tkp_api.models.tenant import User


def hash_password(password: str) -> str:
    """使用 PBKDF2-SHA256 生成口令哈希。"""
    settings = get_settings()
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        settings.auth_password_hash_iterations,
    )
    salt_b64 = base64.b64encode(salt).decode("ascii")
    digest_b64 = base64.b64encode(digest).decode("ascii")
    return f"pbkdf2_sha256${settings.auth_password_hash_iterations}${salt_b64}${digest_b64}"


def verify_password(password: str, password_hash: str) -> bool:
    """校验口令是否匹配。"""
    try:
        algorithm, iterations_text, salt_b64, expected_digest_b64 = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_text)
        salt = base64.b64decode(salt_b64.encode("ascii"))
        expected_digest = base64.b64decode(expected_digest_b64.encode("ascii"))
    except (ValueError, TypeError, binascii.Error):
        return False

    actual_digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(actual_digest, expected_digest)


def issue_access_token(user: User) -> tuple[str, int, datetime]:
    """签发访问令牌。"""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=settings.auth_access_token_ttl_seconds)
    issuer_for_decode = settings.auth_jwt_issuer or settings.auth_local_issuer
    jti = str(uuid4())

    claims: dict[str, object] = {
        "sub": user.external_subject,
        "email": user.email,
        "name": user.display_name,
        "provider": user.auth_provider,
        "iss": issuer_for_decode,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": jti,
    }
    if settings.auth_jwt_audience:
        claims["aud"] = settings.auth_jwt_audience

    token = jwt.encode(claims, settings.auth_jwt_secret, algorithm=settings.auth_algorithms[0])
    return token, int(expires_at.timestamp()), expires_at
