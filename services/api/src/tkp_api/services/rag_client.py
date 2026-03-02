"""API 到 RAG 子服务的 HTTP 客户端。"""

from __future__ import annotations

import json
import threading
import time
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

from fastapi import HTTPException, status

_CIRCUIT_LOCK = threading.Lock()
_CIRCUIT_STATE: dict[str, dict[str, float | int]] = {}


def reset_rag_circuit_breaker() -> None:
    """重置所有 RAG 断路器状态（测试场景使用）。"""
    with _CIRCUIT_LOCK:
        _CIRCUIT_STATE.clear()


def _build_remote_url(base_url: str, path: str) -> str:
    cleaned = base_url.rstrip("/")
    return f"{cleaned}{path}"


def _is_circuit_open(base_url: str) -> float:
    with _CIRCUIT_LOCK:
        state = _CIRCUIT_STATE.get(base_url)
        if not state:
            return 0.0
        open_until = float(state.get("open_until", 0.0) or 0.0)
    if open_until <= time.time():
        return 0.0
    return open_until


def _mark_success(base_url: str) -> None:
    with _CIRCUIT_LOCK:
        _CIRCUIT_STATE[base_url] = {"failures": 0, "open_until": 0.0}


def _mark_failure(base_url: str, *, fail_threshold: int, open_seconds: int) -> None:
    with _CIRCUIT_LOCK:
        state = _CIRCUIT_STATE.setdefault(base_url, {"failures": 0, "open_until": 0.0})
        failures = int(state.get("failures", 0) or 0) + 1
        state["failures"] = failures
        if failures >= fail_threshold:
            state["open_until"] = time.time() + max(1, open_seconds)


def _retryable_http_status(status_code: int) -> bool:
    return status_code in {429, 500, 502, 503, 504}


def _do_request(
    *,
    base_url: str,
    path: str,
    payload: dict[str, Any],
    timeout_seconds: float,
    internal_token: str | None,
) -> dict[str, Any]:
    url = _build_remote_url(base_url, path)
    headers = {"Content-Type": "application/json"}
    if internal_token:
        headers["X-Internal-Token"] = internal_token
    req = urlrequest.Request(
        url=url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=timeout_seconds) as resp:
            body = resp.read().decode("utf-8")
            data = json.loads(body) if body else {}
            if not isinstance(data, dict):
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail={
                        "code": "RAG_UPSTREAM_INVALID_RESPONSE",
                        "message": "RAG 服务返回了非法响应结构。",
                        "details": {"reason": "invalid_response_type", "upstream_url": url},
                    },
                )
            return data
    except urlerror.HTTPError as exc:
        body_text = ""
        try:
            body_text = exc.read().decode("utf-8")
        except Exception:
            body_text = ""
        if _retryable_http_status(exc.code):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "RAG_UPSTREAM_RETRYABLE",
                    "message": "RAG 服务暂时不可用，请稍后重试。",
                    "details": {
                        "reason": "upstream_retryable_http_error",
                        "upstream_url": url,
                        "upstream_status": exc.code,
                        "upstream_body": body_text[:500],
                    },
                },
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "RAG_UPSTREAM_REJECTED",
                "message": "RAG 服务拒绝了请求。",
                "details": {
                    "reason": "upstream_non_retryable_http_error",
                    "upstream_url": url,
                    "upstream_status": exc.code,
                    "upstream_body": body_text[:500],
                },
            },
        ) from exc
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={
                "code": "RAG_TIMEOUT",
                "message": "调用 RAG 服务超时。",
                "details": {"reason": "rag_timeout", "upstream_url": url, "error": str(exc)},
            },
        ) from exc
    except (urlerror.URLError, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "RAG_UNAVAILABLE",
                "message": "RAG 服务当前不可用，请稍后重试。",
                "details": {"reason": "rag_unavailable", "upstream_url": url, "error": str(exc)},
            },
        ) from exc


def _is_retryable_error(exc: HTTPException) -> bool:
    if exc.status_code in {status.HTTP_503_SERVICE_UNAVAILABLE, status.HTTP_504_GATEWAY_TIMEOUT}:
        return True
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    code = str(detail.get("code") or "")
    return code in {"RAG_UNAVAILABLE", "RAG_TIMEOUT", "RAG_UPSTREAM_RETRYABLE"}


def post_rag_json(
    base_url: str,
    path: str,
    payload: dict[str, Any],
    timeout_seconds: float,
    *,
    internal_token: str | None,
    max_retries: int,
    retry_backoff_seconds: float,
    circuit_fail_threshold: int,
    circuit_open_seconds: int,
) -> dict[str, Any]:
    """向 RAG 服务发送 JSON 请求（带重试与基础断路器）。"""
    open_until = _is_circuit_open(base_url)
    if open_until > 0:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "RAG_CIRCUIT_OPEN",
                "message": "RAG 服务熔断中，请稍后重试。",
                "details": {
                    "reason": "rag_circuit_open",
                    "open_until": open_until,
                    "upstream_base_url": base_url,
                },
            },
        )

    total_attempts = max(1, max_retries + 1)
    last_error: HTTPException | None = None
    for attempt in range(total_attempts):
        try:
            data = _do_request(
                base_url=base_url,
                path=path,
                payload=payload,
                timeout_seconds=timeout_seconds,
                internal_token=internal_token,
            )
            _mark_success(base_url)
            return data
        except HTTPException as exc:
            last_error = exc
            if _is_retryable_error(exc) and attempt < total_attempts - 1:
                sleep_seconds = max(0.0, retry_backoff_seconds) * (2**attempt)
                if sleep_seconds > 0:
                    time.sleep(sleep_seconds)
                continue
            break

    _mark_failure(
        base_url,
        fail_threshold=max(1, circuit_fail_threshold),
        open_seconds=max(1, circuit_open_seconds),
    )
    assert last_error is not None
    raise last_error

