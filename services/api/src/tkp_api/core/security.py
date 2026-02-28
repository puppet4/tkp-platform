"""认证解析与令牌校验工具。"""
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
import re
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
TOKEN_PLACEHOLDER_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail={
        "code": "AUTH_TOKEN_PLACEHOLDER_NOT_RESOLVED",
        "message": "认证失败：Authorization 仍为变量占位符，未替换为真实访问令牌。",
        "details": {
            "reason": "authorization_placeholder_not_resolved",
            "suggestion": "请先调用登录接口获取 access_token，再在请求头中传入 Bearer 真实令牌。",
        },
    },
)

_LOCAL_BLACKLIST: dict[str, int] = {}
_LOCAL_ACTIVE_USER_SESSIONS: dict[str, tuple[str, int]] = {}
_LOCAL_ACTIVE_JTI_SESSIONS: dict[str, tuple[str, int]] = {}
_LOCAL_LOCK = Lock()
_redis_client: Redis | None = None


@dataclass
class AuthenticatedPrincipal:
    """统一认证主体对象。"""

    # 外部身份主体标识（sub）。
    subject: str
    # 认证提供方（issuer）。
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
    expired_user_keys = [key for key, session in _LOCAL_ACTIVE_USER_SESSIONS.items() if session[1] <= now_ts]
    for key in expired_user_keys:
        _LOCAL_ACTIVE_USER_SESSIONS.pop(key, None)
    expired_jti_keys = [key for key, session in _LOCAL_ACTIVE_JTI_SESSIONS.items() if session[1] <= now_ts]
    for key in expired_jti_keys:
        _LOCAL_ACTIVE_JTI_SESSIONS.pop(key, None)


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


def _session_user_key(user_session_id: str) -> str:
    settings = get_settings()
    return f"{settings.auth_token_session_prefix}user:{user_session_id}"


def _session_jti_key(jti: str) -> str:
    settings = get_settings()
    return f"{settings.auth_token_session_prefix}jti:{jti}"


def activate_user_session(*, user_session_id: str, jti: str, exp_ts: int) -> None:
    """激活用户当前会话（单点登录：每个用户仅保留一个 jti）。"""
    now_ts = int(datetime.now(timezone.utc).timestamp())
    ttl = max(1, exp_ts - now_ts)
    redis_client = _get_redis()
    if redis_client is not None:
        try:
            user_key = _session_user_key(user_session_id)
            previous_jti = redis_client.get(user_key)
            pipe = redis_client.pipeline()
            pipe.setex(user_key, ttl, jti)
            pipe.setex(_session_jti_key(jti), ttl, user_session_id)
            if previous_jti and previous_jti != jti:
                pipe.delete(_session_jti_key(previous_jti))
            pipe.execute()
            return
        except RedisError:
            # Redis 不可用时，回退到本地缓存，保证会话控制尽量可用。
            pass

    with _LOCAL_LOCK:
        _cleanup_local(now_ts)
        previous = _LOCAL_ACTIVE_USER_SESSIONS.get(user_session_id)
        if previous and previous[0] != jti:
            _LOCAL_ACTIVE_JTI_SESSIONS.pop(previous[0], None)
        _LOCAL_ACTIVE_USER_SESSIONS[user_session_id] = (jti, exp_ts)
        _LOCAL_ACTIVE_JTI_SESSIONS[jti] = (user_session_id, exp_ts)


def clear_user_session(*, user_session_id: str, jti: str) -> None:
    """清理指定用户会话。"""
    redis_client = _get_redis()
    if redis_client is not None:
        try:
            user_key = _session_user_key(user_session_id)
            current_jti = redis_client.get(user_key)
            pipe = redis_client.pipeline()
            pipe.delete(_session_jti_key(jti))
            if current_jti == jti:
                pipe.delete(user_key)
            pipe.execute()
            return
        except RedisError:
            pass

    now_ts = int(datetime.now(timezone.utc).timestamp())
    with _LOCAL_LOCK:
        _cleanup_local(now_ts)
        _LOCAL_ACTIVE_JTI_SESSIONS.pop(jti, None)
        current = _LOCAL_ACTIVE_USER_SESSIONS.get(user_session_id)
        if current and current[0] == jti:
            _LOCAL_ACTIVE_USER_SESSIONS.pop(user_session_id, None)


def is_user_session_active(*, user_session_id: str, jti: str) -> bool:
    """判断用户当前会话 jti 是否仍有效。"""
    redis_client = _get_redis()
    if redis_client is not None:
        try:
            current_jti = redis_client.get(_session_user_key(user_session_id))
            if not current_jti or current_jti != jti:
                return False
            jti_owner = redis_client.get(_session_jti_key(jti))
            return bool(jti_owner and jti_owner == user_session_id)
        except RedisError:
            pass

    now_ts = int(datetime.now(timezone.utc).timestamp())
    with _LOCAL_LOCK:
        _cleanup_local(now_ts)
        current = _LOCAL_ACTIVE_USER_SESSIONS.get(user_session_id)
        if not current or current[0] != jti or current[1] <= now_ts:
            return False
        jti_session = _LOCAL_ACTIVE_JTI_SESSIONS.get(jti)
        return bool(jti_session and jti_session[0] == user_session_id and jti_session[1] > now_ts)


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


def _validate_runtime_token_state(claims: dict[str, Any]) -> None:
    """校验令牌运行时状态（黑名单 + 单点登录会话）。"""
    jti = claims.get("jti")
    if not isinstance(jti, str) or not jti:
        return
    if is_token_jti_revoked(jti):
        raise UNAUTHORIZED

    session_uid = claims.get("tkp_uid")
    if isinstance(session_uid, str) and session_uid and not is_user_session_active(user_session_id=session_uid, jti=jti):
        raise UNAUTHORIZED


def _is_placeholder_token(token: str) -> bool:
    return ("{{" in token and "}}" in token) or ("${" in token and "}" in token)


def _extract_bearer_token(authorization: str | None) -> str:
    """从 Authorization 头中提取 Bearer token，兼容重复头被逗号拼接的场景。"""
    if not authorization:
        raise UNAUTHORIZED
    tokens = re.findall(r"Bearer\s+([^,\s]+)", authorization, flags=re.IGNORECASE)
    if not tokens:
        raise UNAUTHORIZED
    placeholder_seen = False
    for candidate in reversed(tokens):
        token = candidate.strip()
        if not token:
            continue
        if _is_placeholder_token(token):
            placeholder_seen = True
            continue
        return token
    if placeholder_seen:
        raise TOKEN_PLACEHOLDER_UNAUTHORIZED
    raise UNAUTHORIZED


def parse_authorization_header(authorization: str | None) -> AuthenticatedPrincipal:
    """解析认证头并返回认证主体。"""
    token = _extract_bearer_token(authorization)
    if _is_placeholder_token(token):
        raise TOKEN_PLACEHOLDER_UNAUTHORIZED

    claims = _decode_jwt(token)
    _validate_runtime_token_state(claims)

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
