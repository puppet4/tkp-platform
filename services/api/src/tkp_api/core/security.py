"""认证解析与令牌校验工具。"""

from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from threading import Lock
from typing import Any

import jwt
from fastapi import HTTPException, status
from jwt import InvalidTokenError, PyJWKClient

from tkp_api.core.config import get_settings

try:
    from redis import Redis
    from redis.exceptions import RedisError
except ImportError:  # pragma: no cover - 依赖缺失时自动回退到本地缓存
    Redis = Any  # type: ignore[assignment]

    class RedisError(Exception):
        pass

UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="unauthorized",
)

_LOCAL_BLACKLIST: dict[str, int] = {}
_LOCAL_LOCK = Lock()
_redis_client: Redis | None = None


@dataclass
class AuthenticatedPrincipal:
    """统一认证主体对象。"""

    # 外部身份主体标识（sub）。
    subject: str
    # 认证提供方（issuer 或 dev）。
    provider: str
    # 可选邮箱。
    email: str | None
    # 可选展示名。
    display_name: str | None
    # 原始声明集，便于下游扩展。
    claims: dict[str, Any]


@lru_cache
def _get_jwks_client(jwks_url: str) -> PyJWKClient:
    """缓存密钥集合客户端，减少重复网络开销。"""
    return PyJWKClient(jwks_url)


def _decode_jwt(token: str) -> dict[str, Any]:
    """按配置解码并校验令牌。"""
    settings = get_settings()
    algorithms = settings.auth_algorithms
    options = {"verify_signature": True, "verify_aud": bool(settings.auth_jwt_audience)}

    try:
        if settings.auth_jwks_url:
            # 生产建议使用 JWKS，支持密钥轮换。
            key = _get_jwks_client(settings.auth_jwks_url).get_signing_key_from_jwt(token).key
            return jwt.decode(
                token,
                key=key,
                algorithms=algorithms,
                issuer=settings.auth_jwt_issuer,
                audience=settings.auth_jwt_audience,
                leeway=settings.auth_jwt_leeway_seconds,
                options=options,
            )

        # 未配置 JWKS 时，回退到对称密钥校验（适合本地开发/测试）。
        return jwt.decode(
            token,
            key=settings.auth_jwt_secret,
            algorithms=algorithms,
            issuer=settings.auth_jwt_issuer,
            audience=settings.auth_jwt_audience,
            leeway=settings.auth_jwt_leeway_seconds,
            options=options,
        )
    except InvalidTokenError as exc:
        raise UNAUTHORIZED from exc


def _cleanup_local(now_ts: int) -> None:
    expired_keys = [key for key, expires_at in _LOCAL_BLACKLIST.items() if expires_at <= now_ts]
    for key in expired_keys:
        _LOCAL_BLACKLIST.pop(key, None)


def _get_redis() -> Redis | None:
    global _redis_client
    settings = get_settings()
    if not settings.redis_url or Redis is Any:
        return None
    if _redis_client is None:
        _redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


def _key_for_jti(jti: str) -> str:
    settings = get_settings()
    return f"{settings.auth_token_blacklist_prefix}{jti}"


def revoke_token_jti(jti: str, exp_ts: int) -> None:
    """将 token jti 拉黑到令牌过期时间。"""
    now_ts = int(datetime.now(timezone.utc).timestamp())
    ttl = max(1, exp_ts - now_ts)
    redis_client = _get_redis()
    if redis_client is not None:
        try:
            redis_client.setex(_key_for_jti(jti), ttl, "1")
            return
        except RedisError:
            # Redis 不可用时，回退到本地缓存，保证登出语义尽量可用。
            pass

    with _LOCAL_LOCK:
        _cleanup_local(now_ts)
        _LOCAL_BLACKLIST[jti] = exp_ts


def is_token_jti_revoked(jti: str) -> bool:
    """判断 token jti 是否已被拉黑。"""
    redis_client = _get_redis()
    if redis_client is not None:
        try:
            return bool(redis_client.exists(_key_for_jti(jti)))
        except RedisError:
            pass

    now_ts = int(datetime.now(timezone.utc).timestamp())
    with _LOCAL_LOCK:
        _cleanup_local(now_ts)
        expires_at = _LOCAL_BLACKLIST.get(jti)
        return expires_at is not None and expires_at > now_ts


def parse_authorization_header(authorization: str | None) -> AuthenticatedPrincipal:
    """解析认证头并返回认证主体。"""
    if not authorization or not authorization.startswith("Bearer "):
        raise UNAUTHORIZED

    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise UNAUTHORIZED

    settings = get_settings()
    if settings.auth_mode == "dev":
        # 开发模式下将 token 直接视为用户主体，降低本地联调门槛。
        subject = token.removeprefix("dev:") if token.startswith("dev:") else token
        return AuthenticatedPrincipal(
            subject=subject,
            provider="dev",
            email=f"{subject}@local.dev",
            display_name=f"user-{subject[:8]}",
            claims={"sub": subject},
        )

    claims = _decode_jwt(token)
    jti = claims.get("jti")
    if isinstance(jti, str) and jti and is_token_jti_revoked(jti):
        raise UNAUTHORIZED

    subject = str(claims.get("sub") or "").strip()
    if not subject:
        raise UNAUTHORIZED

    email = claims.get("email")
    display_name = claims.get("name") or claims.get("preferred_username")
    provider = claims.get("provider")
    issuer = str(provider if isinstance(provider, str) and provider else (claims.get("iss") or "jwt"))

    return AuthenticatedPrincipal(
        subject=subject,
        provider=issuer,
        email=email if isinstance(email, str) else None,
        display_name=display_name if isinstance(display_name, str) else None,
        claims=claims,
    )
