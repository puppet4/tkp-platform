"""本地账号认证服务。"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
import time
from datetime import datetime, timedelta, timezone
from uuid import UUID
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


def issue_access_token(user: User, *, tenant_id: UUID | None = None) -> tuple[str, int, datetime, str]:
    """签发访问令牌。"""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=settings.auth_access_token_ttl_seconds)
    issuer_for_decode = settings.auth_jwt_issuer or settings.auth_local_issuer
    jti = str(uuid4())

    claims: dict[str, object] = {
        "sub": user.external_subject,
        "tkp_uid": str(user.id),
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
    if tenant_id is not None:
        claims["tenant_id"] = str(tenant_id)

    token = jwt.encode(claims, settings.auth_jwt_secret.get_secret_value(), algorithm=settings.auth_algorithms[0])
    return token, int(expires_at.timestamp()), expires_at, jti


def generate_totp_secret(*, byte_length: int = 20) -> str:
    """生成 Base32 TOTP 密钥。"""
    raw = secrets.token_bytes(byte_length)
    return base64.b32encode(raw).decode("ascii").replace("=", "")


def _normalize_base32(secret: str) -> bytes:
    normalized = secret.strip().replace(" ", "").upper()
    padding = "=" * ((8 - (len(normalized) % 8)) % 8)
    return base64.b32decode(normalized + padding, casefold=True)


def generate_totp_code(
    secret: str,
    *,
    for_time: int | None = None,
    period_seconds: int = 30,
    digits: int = 6,
) -> str:
    """按 RFC6238 生成 TOTP。"""
    if for_time is None:
        for_time = int(time.time())
    counter = int(for_time // period_seconds)
    key = _normalize_base32(secret)
    msg = counter.to_bytes(8, byteorder="big")
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code_int = (
        ((digest[offset] & 0x7F) << 24)
        | (digest[offset + 1] << 16)
        | (digest[offset + 2] << 8)
        | digest[offset + 3]
    )
    code = code_int % (10**digits)
    return f"{code:0{digits}d}"


def verify_totp_code(
    secret: str,
    *,
    code: str,
    for_time: int | None = None,
    period_seconds: int = 30,
    digits: int = 6,
    valid_window: int = 1,
    last_used_counter: int | None = None,
) -> tuple[bool, int | None]:
    """校验 TOTP 码；返回是否通过与匹配计数器。"""
    if not code.isdigit() or len(code) != digits:
        return False, None
    if for_time is None:
        for_time = int(time.time())
    current_counter = int(for_time // period_seconds)

    for delta in range(-valid_window, valid_window + 1):
        counter = current_counter + delta
        if counter < 0:
            continue
        if last_used_counter is not None and counter <= last_used_counter:
            continue
        expected = generate_totp_code(
            secret,
            for_time=counter * period_seconds,
            period_seconds=period_seconds,
            digits=digits,
        )
        if hmac.compare_digest(expected, code):
            return True, counter
    return False, None


def issue_mfa_challenge_token(
    user: User,
    *,
    tenant_id: UUID | None = None,
    ttl_seconds: int = 300,
) -> tuple[str, int]:
    """签发 MFA 二阶段挑战令牌。"""
    settings = get_settings()
    now_ts = int(datetime.now(timezone.utc).timestamp())
    exp_ts = now_ts + ttl_seconds
    issuer_for_decode = settings.auth_jwt_issuer or settings.auth_local_issuer

    claims: dict[str, object] = {
        "sub": user.external_subject,
        "tkp_uid": str(user.id),
        "email": user.email,
        "name": user.display_name,
        "provider": user.auth_provider,
        "iss": issuer_for_decode,
        "iat": now_ts,
        "exp": exp_ts,
        "jti": str(uuid4()),
        "purpose": "mfa_login",
    }
    if settings.auth_jwt_audience:
        claims["aud"] = settings.auth_jwt_audience
    if tenant_id is not None:
        claims["tenant_id"] = str(tenant_id)

    token = jwt.encode(claims, settings.auth_jwt_secret.get_secret_value(), algorithm=settings.auth_algorithms[0])
    return token, exp_ts


def decode_mfa_challenge_token(token: str) -> dict[str, object]:
    """校验并解码 MFA 挑战令牌。"""
    settings = get_settings()
    claims = jwt.decode(
        token,
        key=settings.auth_jwt_secret.get_secret_value(),
        algorithms=settings.auth_algorithms,
        issuer=settings.auth_jwt_issuer,
        audience=settings.auth_jwt_audience,
        leeway=settings.auth_jwt_leeway_seconds,
        options={"verify_signature": True, "verify_aud": bool(settings.auth_jwt_audience)},
    )
    if not isinstance(claims, dict):
        raise jwt.InvalidTokenError("invalid challenge token")
    if claims.get("purpose") != "mfa_login":
        raise jwt.InvalidTokenError("invalid challenge purpose")
    return dict(claims)
