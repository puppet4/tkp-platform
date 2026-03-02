import json
import os
import time
from collections.abc import Generator
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pgvector.sqlalchemy import Vector
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import tkp_api.models  # noqa: F401
from tkp_api.core import security as security_module
from tkp_api.core.config import get_settings
from tkp_api.db.session import get_db
from tkp_api.db.session import engine as app_engine
from tkp_api.main import app
from tkp_api.models.base import Base


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type_, _compiler, **_kwargs):
    return "JSON"


@compiles(INET, "sqlite")
def _compile_inet_sqlite(_type_, _compiler, **_kwargs):
    return "TEXT"


@compiles(Vector, "sqlite")
def _compile_vector_sqlite(_type_, _compiler, **_kwargs):
    return "BLOB"


class _StopWorkflow(Exception):
    """命中单接口目标后提前结束流程。"""


@dataclass
class WorkflowContext:
    """跨阶段共享的业务数据。"""

    pwd: str
    owner_email: str
    member_email: str
    user3_email: str
    user4_email: str
    owner_user_id: str = ""
    member_user_id: str = ""
    owner_token: str = ""
    member_token: str = ""
    owner_personal_tenant_id: str = ""
    enterprise_tenant_id: str = ""
    enterprise_tenant_slug: str = ""
    enterprise_default_workspace_id: str = ""
    ws1_id: str = ""
    ws2_id: str = ""
    kb1_id: str = ""
    kb2_id: str = ""
    document_id: str = ""
    run_id: str = ""
    user3_id: str = ""
    user4_id: str = ""


def _assert_non_empty_str(value: object, field: str) -> None:
    assert isinstance(value, str), f"{field} should be str, got {type(value).__name__}"
    assert value.strip(), f"{field} should not be empty"


def _assert_uuid(value: object, field: str) -> None:
    _assert_non_empty_str(value, field)
    UUID(value)


def _assert_iso_datetime(value: object, field: str) -> None:
    _assert_non_empty_str(value, field)
    datetime.fromisoformat(value.replace("Z", "+00:00"))


def _require_keys(data: dict, keys: list[str], where: str) -> None:
    missing = [k for k in keys if k not in data]
    assert not missing, f"{where} missing keys: {missing}"


def _find_one(items: list[dict], *, where: str, **conditions):
    for item in items:
        if all(item.get(k) == v for k, v in conditions.items()):
            return item
    raise AssertionError(f"{where} not found with conditions={conditions}, total={len(items)}")


def _is_verbose_log_enabled() -> bool:
    """更细粒度日志开关，默认开启。"""
    return os.getenv("TKP_TEST_LOG_VERBOSE", "1").strip() not in {"0", "false", "False"}


def _is_payload_log_enabled() -> bool:
    """响应体内容日志开关，默认关闭，避免终端过载。"""
    return os.getenv("TKP_TEST_LOG_PAYLOAD", "0").strip() not in {"0", "false", "False"}


def _preview_value(value: Any, *, max_len: int = 220) -> str:
    """将复杂对象转为可读且受控长度的日志片段。"""
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        text = repr(value)
    text = text.replace("\n", " ")
    return text if len(text) <= max_len else f"{text[:max_len]}..."


class WorkflowRunner:
    """封装 HTTP 流程执行，提供可追踪日志与强校验。"""

    def __init__(self, api_client: TestClient, *, stop_at: tuple[str, str] | None = None) -> None:
        self.api_client = api_client
        self.stop_at = stop_at
        self.covered: set[tuple[str, str]] = set()
        self.stop_hit = False
        self.started_at = time.perf_counter()
        self._current_stage_name: str | None = None
        self._current_stage_started_at: float | None = None
        self.ctx = WorkflowContext(
            pwd="StrongPassw0rd!",
            owner_email=f"owner-{uuid4().hex[:8]}@example.com",
            member_email=f"member-{uuid4().hex[:8]}@example.com",
            user3_email=f"user3-{uuid4().hex[:8]}@example.com",
            user4_email=f"user4-{uuid4().hex[:8]}@example.com",
        )

    def elapsed(self) -> float:
        return time.perf_counter() - self.started_at

    def stage(self, name: str) -> None:
        # 新阶段开始前，先输出上一阶段耗时，形成完整链路日志。
        if self._current_stage_name and self._current_stage_started_at is not None:
            duration = time.perf_counter() - self._current_stage_started_at
            _log(f"[STEP-END] {self._current_stage_name} | elapsed={duration:.2f}s")
        self._current_stage_name = name
        self._current_stage_started_at = time.perf_counter()
        _log(f"[STEP-START] {name}")

    def _finish_current_stage(self) -> None:
        if self._current_stage_name and self._current_stage_started_at is not None:
            duration = time.perf_counter() - self._current_stage_started_at
            _log(f"[STEP-END] {self._current_stage_name} | elapsed={duration:.2f}s")
        self._current_stage_name = None
        self._current_stage_started_at = None

    def trace(self, label: str, **fields: Any) -> None:
        if not _is_verbose_log_enabled():
            return
        serialized = ", ".join(f"{k}={_preview_value(v)}" for k, v in fields.items())
        _log(f"[TRACE] {label} | {serialized}")

    def _summarize_request_args(self, kwargs: dict[str, Any]) -> str:
        parts: list[str] = []
        if "json" in kwargs:
            payload = kwargs["json"]
            if isinstance(payload, dict):
                parts.append(f"json_keys={sorted(payload.keys())}")
            else:
                parts.append(f"json_type={type(payload).__name__}")
        if "data" in kwargs:
            payload = kwargs["data"]
            if isinstance(payload, dict):
                parts.append(f"form_keys={sorted(payload.keys())}")
            else:
                parts.append(f"form_type={type(payload).__name__}")
        if "files" in kwargs and isinstance(kwargs["files"], dict):
            parts.append(f"file_fields={sorted(kwargs['files'].keys())}")
        if "params" in kwargs and isinstance(kwargs["params"], dict):
            parts.append(f"query_keys={sorted(kwargs['params'].keys())}")
        if not parts:
            return "no-body"
        return ", ".join(parts)

    def _assert_success_envelope(self, payload: object, *, method: str, path: str) -> dict:
        assert isinstance(payload, dict), f"success payload should be object, got {type(payload).__name__}"
        _require_keys(payload, ["request_id", "data", "meta"], "success payload")

        _assert_non_empty_str(payload["request_id"], "request_id")

        meta = payload["meta"]
        assert isinstance(meta, dict), "meta should be object"
        _require_keys(meta, ["message", "method", "path", "timestamp", "process_ms"], "success meta")
        _assert_non_empty_str(meta["message"], "meta.message")
        assert meta["method"] == method.upper(), f"meta.method mismatch: {meta['method']} != {method.upper()}"
        assert meta["path"] == path, f"meta.path mismatch: {meta['path']} != {path}"
        _assert_iso_datetime(meta["timestamp"], "meta.timestamp")
        assert meta["process_ms"] is None or (
            isinstance(meta["process_ms"], int) and meta["process_ms"] >= 0
        ), "meta.process_ms should be null or non-negative integer"

        return payload["data"]

    def _assert_error_envelope(self, payload: object, *, method: str, path: str, expected_status: int) -> dict:
        assert isinstance(payload, dict), f"error payload should be object, got {type(payload).__name__}"
        _require_keys(payload, ["request_id", "error"], "error payload")
        _assert_non_empty_str(payload["request_id"], "request_id")

        error = payload["error"]
        assert isinstance(error, dict), "error should be object"
        _require_keys(error, ["code", "message", "details"], "error body")
        _assert_non_empty_str(error["code"], "error.code")
        _assert_non_empty_str(error["message"], "error.message")

        details = error["details"]
        assert isinstance(details, dict), "error.details should be object"
        _require_keys(details, ["method", "path", "timestamp"], "error.details")
        assert details["method"] == method.upper(), f"error.details.method mismatch: {details['method']} != {method.upper()}"
        assert details["path"] == path, f"error.details.path mismatch: {details['path']} != {path}"
        _assert_iso_datetime(details["timestamp"], "error.details.timestamp")

        if "status_code" in details:
            assert details["status_code"] == expected_status, (
                f"error.details.status_code mismatch: {details['status_code']} != {expected_status}"
            )
        if "reason" in details:
            _assert_non_empty_str(details["reason"], "error.details.reason")
        if "suggestion" in details:
            _assert_non_empty_str(details["suggestion"], "error.details.suggestion")
        return error

    def call(
        self,
        method: str,
        template_path: str,
        *,
        actual_path: str | None = None,
        token: str | None = None,
        expected_status: int = 200,
        allow_stop: bool = True,
        **kwargs,
    ):
        self.covered.add((method.upper(), template_path))

        path = actual_path or template_path
        headers = dict(kwargs.pop("headers", {}) or {})
        # 避免 PostgreSQL INET 字段被 TestClient 默认 host 值污染。
        headers.setdefault("X-Forwarded-For", "127.0.0.1")
        if token:
            headers["Authorization"] = f"Bearer {token}"

        if _is_verbose_log_enabled():
            self.trace(
                "request",
                method=method.upper(),
                template_path=template_path,
                actual_path=path,
                has_token=bool(token),
                args=self._summarize_request_args(kwargs),
            )
        response = self.api_client.request(method, path, headers=headers, **kwargs)
        _log(f"[API] {method.upper():6} {template_path:<55} -> {response.status_code}")
        if _is_verbose_log_enabled():
            self.trace(
                "response",
                method=method.upper(),
                template_path=template_path,
                status_code=response.status_code,
                content_type=response.headers.get("content-type", ""),
            )
        if _is_payload_log_enabled():
            self.trace("response-body", template_path=template_path, body=response.text)
        assert response.status_code == expected_status, (
            f"{method.upper()} {template_path} expected {expected_status}, "
            f"got {response.status_code}: {response.text}"
        )

        if self.stop_at and allow_stop and (method.upper(), template_path) == self.stop_at:
            self.stop_hit = True
            raise _StopWorkflow()
        return response

    def success(self, method: str, template_path: str, *, expected_status: int = 200, **kwargs) -> dict:
        actual_path = kwargs.get("actual_path") or template_path
        response = self.call(method, template_path, expected_status=expected_status, **kwargs)
        payload = response.json()
        data = self._assert_success_envelope(payload, method=method, path=actual_path)
        if _is_verbose_log_enabled():
            data_summary = sorted(data.keys()) if isinstance(data, dict) else type(data).__name__
            self.trace("assert-success", template_path=template_path, data_summary=data_summary)
        return data

    def expect_error(
        self,
        method: str,
        template_path: str,
        *,
        expected_status: int,
        expected_code: str | None = None,
        allow_stop: bool = True,
        **kwargs,
    ) -> dict:
        actual_path = kwargs.get("actual_path") or template_path
        response = self.call(
            method,
            template_path,
            expected_status=expected_status,
            allow_stop=allow_stop,
            **kwargs,
        )
        payload = response.json()
        error = self._assert_error_envelope(
            payload,
            method=method,
            path=actual_path,
            expected_status=expected_status,
        )
        if expected_code:
            assert error["code"] == expected_code, f"error code mismatch: {error['code']} != {expected_code}"
        if _is_verbose_log_enabled():
            self.trace(
                "assert-error",
                template_path=template_path,
                expected_status=expected_status,
                error_code=error.get("code"),
                reason=(error.get("details") or {}).get("reason"),
            )
        return error

    def _assert_auth_register_data(self, data: dict, *, email: str, display_name: str) -> None:
        _require_keys(
            data,
            [
                "user_id",
                "email",
                "display_name",
                "auth_provider",
                "personal_tenant_id",
                "personal_tenant_slug",
                "personal_tenant_name",
                "default_workspace_id",
            ],
            "auth.register.data",
        )
        _assert_uuid(data["user_id"], "auth.register.user_id")
        assert data["email"] == email
        assert data["display_name"] == display_name
        _assert_non_empty_str(data["auth_provider"], "auth.register.auth_provider")
        _assert_uuid(data["personal_tenant_id"], "auth.register.personal_tenant_id")
        _assert_non_empty_str(data["personal_tenant_slug"], "auth.register.personal_tenant_slug")
        _assert_non_empty_str(data["personal_tenant_name"], "auth.register.personal_tenant_name")
        _assert_uuid(data["default_workspace_id"], "auth.register.default_workspace_id")

    def _assert_auth_login_data(self, data: dict, *, tenant_id: str | None = None) -> None:
        _require_keys(
            data,
            ["access_token", "token_type", "expires_at", "expires_in", "tenant_id"],
            "auth.login.data",
        )
        _assert_non_empty_str(data["access_token"], "auth.login.access_token")
        assert data["access_token"].count(".") == 2, "access_token should look like JWT"
        assert data["token_type"] == "bearer"
        _assert_iso_datetime(data["expires_at"], "auth.login.expires_at")
        assert isinstance(data["expires_in"], int) and data["expires_in"] > 0
        if tenant_id is not None:
            assert data["tenant_id"] == tenant_id
        elif data["tenant_id"] is not None:
            _assert_uuid(data["tenant_id"], "auth.login.tenant_id")

    def _assert_auth_me_data(self, data: dict, *, expected_email: str, expected_user_id: str) -> None:
        _require_keys(data, ["user", "tenants", "workspaces"], "auth.me.data")

        user = data["user"]
        assert isinstance(user, dict), "auth.me.user should be object"
        _require_keys(
            user,
            ["id", "email", "display_name", "status", "auth_provider", "external_subject", "last_login_at"],
            "auth.me.user",
        )
        assert user["id"] == expected_user_id
        assert user["email"] == expected_email
        _assert_non_empty_str(user["display_name"], "auth.me.user.display_name")
        _assert_non_empty_str(user["status"], "auth.me.user.status")
        _assert_non_empty_str(user["auth_provider"], "auth.me.user.auth_provider")
        _assert_non_empty_str(user["external_subject"], "auth.me.user.external_subject")
        if user["last_login_at"] is not None:
            _assert_iso_datetime(user["last_login_at"], "auth.me.user.last_login_at")

        assert isinstance(data["tenants"], list), "auth.me.tenants should be list"
        for item in data["tenants"]:
            _require_keys(item, ["tenant_id", "name", "slug", "role", "status"], "auth.me.tenants[]")
            _assert_uuid(item["tenant_id"], "auth.me.tenants[].tenant_id")
            _assert_non_empty_str(item["name"], "auth.me.tenants[].name")
            _assert_non_empty_str(item["slug"], "auth.me.tenants[].slug")
            _assert_non_empty_str(item["role"], "auth.me.tenants[].role")
            _assert_non_empty_str(item["status"], "auth.me.tenants[].status")

        assert isinstance(data["workspaces"], list), "auth.me.workspaces should be list"
        for item in data["workspaces"]:
            _require_keys(item, ["workspace_id", "tenant_id", "name", "slug", "role", "status"], "auth.me.workspaces[]")
            _assert_uuid(item["workspace_id"], "auth.me.workspaces[].workspace_id")
            _assert_uuid(item["tenant_id"], "auth.me.workspaces[].tenant_id")
            _assert_non_empty_str(item["name"], "auth.me.workspaces[].name")
            _assert_non_empty_str(item["slug"], "auth.me.workspaces[].slug")
            _assert_non_empty_str(item["role"], "auth.me.workspaces[].role")
            _assert_non_empty_str(item["status"], "auth.me.workspaces[].status")

    def _assert_tenant_data(self, data: dict, *, tenant_id: str, name: str | None = None, role: str | None = None, status: str | None = None) -> None:
        _require_keys(data, ["tenant_id", "name", "slug", "status", "role"], "tenant.data")
        assert data["tenant_id"] == tenant_id
        _assert_non_empty_str(data["name"], "tenant.name")
        _assert_non_empty_str(data["slug"], "tenant.slug")
        _assert_non_empty_str(data["status"], "tenant.status")
        _assert_non_empty_str(data["role"], "tenant.role")
        if name is not None:
            assert data["name"] == name
        if role is not None:
            assert data["role"] == role
        if status is not None:
            assert data["status"] == status

    def _assert_tenant_member_data(
        self,
        data: dict,
        *,
        tenant_id: str,
        user_id: str,
        email: str | None = None,
        role: str | None = None,
        status: str | None = None,
    ) -> None:
        _require_keys(data, ["tenant_id", "user_id", "email", "role", "status"], "tenant.member.data")
        assert data["tenant_id"] == tenant_id
        assert data["user_id"] == user_id
        _assert_non_empty_str(data["email"], "tenant.member.email")
        _assert_non_empty_str(data["role"], "tenant.member.role")
        _assert_non_empty_str(data["status"], "tenant.member.status")
        if email is not None:
            assert data["email"] == email
        if role is not None:
            assert data["role"] == role
        if status is not None:
            assert data["status"] == status

    def _assert_role_permission_data(self, data: dict, *, role: str | None = None, contains: set[str] | None = None) -> None:
        _require_keys(data, ["role", "permission_codes"], "role_permission.data")
        _assert_non_empty_str(data["role"], "role_permission.role")
        assert isinstance(data["permission_codes"], list), "permission_codes should be list"
        for code in data["permission_codes"]:
            _assert_non_empty_str(code, "permission_codes[]")
        if role is not None:
            assert data["role"] == role
        if contains is not None:
            assert contains.issubset(set(data["permission_codes"]))

    def _assert_user_data(
        self,
        data: dict,
        *,
        user_id: str,
        email: str | None = None,
        display_name: str | None = None,
        membership_status: str | None = None,
    ) -> None:
        _require_keys(
            data,
            ["user_id", "email", "display_name", "user_status", "tenant_role", "membership_status"],
            "user.data",
        )
        assert data["user_id"] == user_id
        _assert_non_empty_str(data["email"], "user.email")
        _assert_non_empty_str(data["display_name"], "user.display_name")
        _assert_non_empty_str(data["user_status"], "user.user_status")
        _assert_non_empty_str(data["tenant_role"], "user.tenant_role")
        _assert_non_empty_str(data["membership_status"], "user.membership_status")
        if email is not None:
            assert data["email"] == email
        if display_name is not None:
            assert data["display_name"] == display_name
        if membership_status is not None:
            assert data["membership_status"] == membership_status

    def _assert_workspace_data(
        self,
        data: dict,
        *,
        workspace_id: str | None = None,
        name: str | None = None,
        status: str | None = None,
        role: str | None = None,
    ) -> None:
        _require_keys(data, ["id", "name", "slug", "description", "status", "role"], "workspace.data")
        _assert_uuid(data["id"], "workspace.id")
        _assert_non_empty_str(data["name"], "workspace.name")
        _assert_non_empty_str(data["slug"], "workspace.slug")
        assert data["description"] is None or isinstance(data["description"], str)
        _assert_non_empty_str(data["status"], "workspace.status")
        _assert_non_empty_str(data["role"], "workspace.role")
        if workspace_id is not None:
            assert data["id"] == workspace_id
        if name is not None:
            assert data["name"] == name
        if status is not None:
            assert data["status"] == status
        if role is not None:
            assert data["role"] == role

    def _assert_workspace_member_data(
        self,
        data: dict,
        *,
        workspace_id: str,
        user_id: str,
        role: str | None = None,
        status: str | None = None,
    ) -> None:
        _require_keys(data, ["workspace_id", "user_id", "role", "status"], "workspace.member.data")
        assert data["workspace_id"] == workspace_id
        assert data["user_id"] == user_id
        _assert_non_empty_str(data["role"], "workspace.member.role")
        _assert_non_empty_str(data["status"], "workspace.member.status")
        if role is not None:
            assert data["role"] == role
        if status is not None:
            assert data["status"] == status

    def _assert_kb_data(
        self,
        data: dict,
        *,
        kb_id: str | None = None,
        workspace_id: str | None = None,
        name: str | None = None,
        status: str | None = None,
    ) -> None:
        _require_keys(data, ["id", "workspace_id", "name", "description", "embedding_model", "status", "role"], "kb.data")
        _assert_uuid(data["id"], "kb.id")
        _assert_uuid(data["workspace_id"], "kb.workspace_id")
        _assert_non_empty_str(data["name"], "kb.name")
        assert data["description"] is None or isinstance(data["description"], str)
        _assert_non_empty_str(data["embedding_model"], "kb.embedding_model")
        _assert_non_empty_str(data["status"], "kb.status")
        assert data["role"] is None or isinstance(data["role"], str)
        if kb_id is not None:
            assert data["id"] == kb_id
        if workspace_id is not None:
            assert data["workspace_id"] == workspace_id
        if name is not None:
            assert data["name"] == name
        if status is not None:
            assert data["status"] == status

    def _assert_kb_member_data(
        self,
        data: dict,
        *,
        kb_id: str,
        user_id: str,
        role: str | None = None,
        status: str | None = None,
    ) -> None:
        _require_keys(data, ["kb_id", "user_id", "role", "status"], "kb.member.data")
        assert data["kb_id"] == kb_id
        assert data["user_id"] == user_id
        _assert_non_empty_str(data["role"], "kb.member.role")
        _assert_non_empty_str(data["status"], "kb.member.status")
        if role is not None:
            assert data["role"] == role
        if status is not None:
            assert data["status"] == status

    def _assert_document_data(
        self,
        data: dict,
        *,
        document_id: str | None = None,
        kb_id: str | None = None,
        workspace_id: str | None = None,
        title: str | None = None,
        status: str | None = None,
    ) -> None:
        _require_keys(
            data,
            ["id", "workspace_id", "kb_id", "title", "source_type", "source_uri", "current_version", "status", "metadata"],
            "document.data",
        )
        _assert_uuid(data["id"], "document.id")
        _assert_uuid(data["workspace_id"], "document.workspace_id")
        _assert_uuid(data["kb_id"], "document.kb_id")
        _assert_non_empty_str(data["title"], "document.title")
        _assert_non_empty_str(data["source_type"], "document.source_type")
        assert data["source_uri"] is None or isinstance(data["source_uri"], str)
        assert isinstance(data["current_version"], int) and data["current_version"] >= 1
        _assert_non_empty_str(data["status"], "document.status")
        assert data["metadata"] is None or isinstance(data["metadata"], dict)
        if document_id is not None:
            assert data["id"] == document_id
        if kb_id is not None:
            assert data["kb_id"] == kb_id
        if workspace_id is not None:
            assert data["workspace_id"] == workspace_id
        if title is not None:
            assert data["title"] == title
        if status is not None:
            assert data["status"] == status

    def run(self) -> None:
        """按业务顺序执行全链路流程：注册登录 -> 资源创建 -> 权限 -> 清理。"""
        try:
            self.stage_auth_and_health()
            self.stage_tenant_flow()
            self.stage_retrieval_and_agent_flow()
            self.stage_member_join_flow()
            self.stage_permission_flow()
            self.stage_users_and_workspaces_flow()
            self.stage_knowledge_base_and_documents_flow()
            self.stage_cleanup_and_logout()
        except _StopWorkflow:
            self._finish_current_stage()
            return
        self._finish_current_stage()

    def stage_auth_and_health(self) -> None:
        self.stage("注册与登录")
        # 目标：验证认证主链路可用，并验证常见失败场景返回可读错误。

        register_data = self.success(
            "POST",
            "/api/auth/register",
            json={"email": self.ctx.owner_email, "password": self.ctx.pwd, "display_name": "Owner"},
        )
        self._assert_auth_register_data(register_data, email=self.ctx.owner_email, display_name="Owner")
        self.ctx.owner_user_id = register_data["user_id"]
        self.ctx.owner_personal_tenant_id = register_data["personal_tenant_id"]
        self.trace(
            "owner-bootstrap",
            owner_user_id=self.ctx.owner_user_id,
            owner_email=self.ctx.owner_email,
            personal_tenant_id=self.ctx.owner_personal_tenant_id,
        )

        # 负例：重复注册同邮箱应报冲突，且错误码明确。
        self.expect_error(
            "POST",
            "/api/auth/register",
            expected_status=409,
            expected_code="REGISTER_CREDENTIAL_EXISTS",
            json={"email": self.ctx.owner_email, "password": self.ctx.pwd, "display_name": "Owner"},
        )

        owner_login = self.success(
            "POST",
            "/api/auth/login",
            json={"email": self.ctx.owner_email, "password": self.ctx.pwd},
        )
        self._assert_auth_login_data(owner_login)
        self.ctx.owner_token = owner_login["access_token"]

        # 负例：错误密码应返回 401 与明确业务错误码。
        self.expect_error(
            "POST",
            "/api/auth/login",
            expected_status=401,
            expected_code="LOGIN_INVALID_CREDENTIALS",
            json={"email": self.ctx.owner_email, "password": "WrongPassw0rd!"},
        )

        me_data = self.success("GET", "/api/auth/me", token=self.ctx.owner_token)
        self._assert_auth_me_data(me_data, expected_email=self.ctx.owner_email, expected_user_id=self.ctx.owner_user_id)

        live_data = self.success("GET", "/api/health/live")
        assert live_data == {"status": "ok"}

        ready_data = self.success("GET", "/api/health/ready")
        assert ready_data == {"status": "ready"}

    def stage_tenant_flow(self) -> None:
        self.stage("租户流程")
        # 目标：覆盖租户创建、切换、成员查询、更新，以及冲突负例。

        self.ctx.enterprise_tenant_slug = f"enterprise-{uuid4().hex[:8]}"
        tenant = self.success(
            "POST",
            "/api/tenants",
            token=self.ctx.owner_token,
            json={"name": "Enterprise A", "slug": self.ctx.enterprise_tenant_slug},
        )
        _require_keys(tenant, ["tenant_id", "name", "slug", "role", "default_workspace_id"], "tenant.create.data")
        self.ctx.enterprise_tenant_id = tenant["tenant_id"]
        self.ctx.enterprise_default_workspace_id = tenant["default_workspace_id"]
        self.trace(
            "tenant-created",
            enterprise_tenant_id=self.ctx.enterprise_tenant_id,
            enterprise_tenant_slug=self.ctx.enterprise_tenant_slug,
            default_workspace_id=self.ctx.enterprise_default_workspace_id,
        )
        _assert_uuid(tenant["tenant_id"], "tenant.create.tenant_id")
        _assert_uuid(tenant["default_workspace_id"], "tenant.create.default_workspace_id")
        assert tenant["name"] == "Enterprise A"
        assert tenant["slug"] == self.ctx.enterprise_tenant_slug
        assert tenant["role"] == "owner"

        # 负例：同 slug 再创建应冲突。
        self.expect_error(
            "POST",
            "/api/tenants",
            expected_status=409,
            token=self.ctx.owner_token,
            json={"name": "Enterprise A Dup", "slug": self.ctx.enterprise_tenant_slug},
        )

        tenants_before_switch = self.success("GET", "/api/tenants", token=self.ctx.owner_token)
        assert isinstance(tenants_before_switch, list)
        _find_one(tenants_before_switch, where="owner tenant list", tenant_id=self.ctx.owner_personal_tenant_id)
        _find_one(tenants_before_switch, where="owner tenant list", tenant_id=self.ctx.enterprise_tenant_id)

        switched = self.success(
            "POST",
            "/api/auth/switch-tenant",
            token=self.ctx.owner_token,
            json={"tenant_id": self.ctx.enterprise_tenant_id},
        )
        self._assert_auth_login_data(switched, tenant_id=self.ctx.enterprise_tenant_id)
        self.ctx.owner_token = switched["access_token"]

        owner_me_after_switch = self.success("GET", "/api/auth/me", token=self.ctx.owner_token)
        self._assert_auth_me_data(
            owner_me_after_switch,
            expected_email=self.ctx.owner_email,
            expected_user_id=self.ctx.owner_user_id,
        )
        _find_one(
            owner_me_after_switch["tenants"],
            where="owner me tenants after switch",
            tenant_id=self.ctx.enterprise_tenant_id,
        )

        members_data = self.success(
            "GET",
            "/api/tenants/{tenant_id}/members",
            actual_path=f"/api/tenants/{self.ctx.enterprise_tenant_id}/members",
            token=self.ctx.owner_token,
        )
        assert isinstance(members_data, list)
        owner_member = _find_one(
            members_data,
            where="tenant members",
            user_id=self.ctx.owner_user_id,
        )
        self._assert_tenant_member_data(
            owner_member,
            tenant_id=self.ctx.enterprise_tenant_id,
            user_id=self.ctx.owner_user_id,
            email=self.ctx.owner_email,
            role="owner",
            status="active",
        )

        updated = self.success(
            "PATCH",
            "/api/tenants/{tenant_id}",
            actual_path=f"/api/tenants/{self.ctx.enterprise_tenant_id}",
            token=self.ctx.owner_token,
            json={"name": "Enterprise A Updated"},
        )
        self._assert_tenant_data(
            updated,
            tenant_id=self.ctx.enterprise_tenant_id,
            name="Enterprise A Updated",
            role="owner",
            status="active",
        )

        tenants_after_update = self.success("GET", "/api/tenants", token=self.ctx.owner_token)
        enterprise_after_update = _find_one(
            tenants_after_update,
            where="tenant list after update",
            tenant_id=self.ctx.enterprise_tenant_id,
        )
        assert enterprise_after_update["name"] == "Enterprise A Updated"

    def stage_retrieval_and_agent_flow(self) -> None:
        self.stage("检索与对话流程")
        # 目标：覆盖 retrieval/chat/agent 的成功链路与关键返回结构。

        retrieval_data = self.success(
            "POST",
            "/api/retrieval/query",
            token=self.ctx.owner_token,
            json={"query": "hello", "kb_ids": [], "top_k": 3, "filters": {}, "with_citations": True},
        )
        _require_keys(retrieval_data, ["hits", "latency_ms"], "retrieval.query.data")
        assert isinstance(retrieval_data["hits"], list)
        assert isinstance(retrieval_data["latency_ms"], int) and retrieval_data["latency_ms"] >= 0
        for hit in retrieval_data["hits"]:
            _require_keys(hit, ["chunk_id", "document_id", "document_version_id", "kb_id", "score", "snippet"], "retrieval.hit")
            _assert_uuid(hit["chunk_id"], "retrieval.hit.chunk_id")
            _assert_uuid(hit["document_id"], "retrieval.hit.document_id")
            _assert_uuid(hit["document_version_id"], "retrieval.hit.document_version_id")
            _assert_uuid(hit["kb_id"], "retrieval.hit.kb_id")
            assert isinstance(hit["score"], int)
            _assert_non_empty_str(hit["snippet"], "retrieval.hit.snippet")

        chat_data = self.success(
            "POST",
            "/api/chat/completions",
            token=self.ctx.owner_token,
            json={
                "messages": [{"role": "user", "content": "请回答测试问题"}],
                "kb_ids": [],
                "generation": {"temperature": 0.2, "max_tokens": 128},
            },
        )
        _require_keys(chat_data, ["message_id", "answer", "citations", "usage", "conversation_id"], "chat.data")
        _assert_uuid(chat_data["message_id"], "chat.message_id")
        _assert_non_empty_str(chat_data["answer"], "chat.answer")
        _assert_uuid(chat_data["conversation_id"], "chat.conversation_id")
        assert isinstance(chat_data["citations"], list)
        assert isinstance(chat_data["usage"], dict)
        _require_keys(chat_data["usage"], ["prompt_tokens", "completion_tokens", "total_tokens"], "chat.usage")
        assert chat_data["usage"]["total_tokens"] == (
            chat_data["usage"]["prompt_tokens"] + chat_data["usage"]["completion_tokens"]
        )

        run_data = self.success(
            "POST",
            "/api/agent/runs",
            token=self.ctx.owner_token,
            json={
                "conversation_id": chat_data["conversation_id"],
                "task": "run task",
                "kb_ids": [],
                "tool_policy": {},
            },
        )
        _require_keys(run_data, ["run_id", "status"], "agent.run.create.data")
        self.ctx.run_id = run_data["run_id"]
        self.trace("agent-run-created", run_id=self.ctx.run_id, owner_user_id=self.ctx.owner_user_id)
        _assert_uuid(self.ctx.run_id, "agent.run_id")
        _assert_non_empty_str(run_data["status"], "agent.status")

        run_detail = self.success(
            "GET",
            "/api/agent/runs/{run_id}",
            actual_path=f"/api/agent/runs/{self.ctx.run_id}",
            token=self.ctx.owner_token,
        )
        _require_keys(
            run_detail,
            ["run_id", "status", "plan_json", "tool_calls", "cost", "started_at", "finished_at"],
            "agent.run.detail",
        )
        assert run_detail["run_id"] == self.ctx.run_id
        assert isinstance(run_detail["plan_json"], dict)
        assert isinstance(run_detail["tool_calls"], list)
        assert isinstance(run_detail["cost"], (float, int))
        if run_detail["started_at"] is not None:
            _assert_iso_datetime(run_detail["started_at"], "agent.started_at")
        if run_detail["finished_at"] is not None:
            _assert_iso_datetime(run_detail["finished_at"], "agent.finished_at")

        cancel_data = self.success(
            "POST",
            "/api/agent/runs/{run_id}/cancel",
            actual_path=f"/api/agent/runs/{self.ctx.run_id}/cancel",
            token=self.ctx.owner_token,
        )
        _require_keys(cancel_data, ["run_id", "status"], "agent.run.cancel.data")
        assert cancel_data["run_id"] == self.ctx.run_id
        _assert_non_empty_str(cancel_data["status"], "agent.cancel.status")

    def stage_member_join_flow(self) -> None:
        self.stage("成员加入流程")
        # 目标：覆盖“被邀请 -> 加入 -> 切换租户”的完整成员入驻闭环。

        member_register = self.success(
            "POST",
            "/api/auth/register",
            json={"email": self.ctx.member_email, "password": self.ctx.pwd, "display_name": "Member"},
        )
        self._assert_auth_register_data(member_register, email=self.ctx.member_email, display_name="Member")
        self.ctx.member_user_id = member_register["user_id"]
        self.trace("member-registered", member_user_id=self.ctx.member_user_id, member_email=self.ctx.member_email)

        member_login = self.success(
            "POST",
            "/api/auth/login",
            json={"email": self.ctx.member_email, "password": self.ctx.pwd},
        )
        self._assert_auth_login_data(member_login)
        self.ctx.member_token = member_login["access_token"]

        invited = self.success(
            "POST",
            "/api/tenants/{tenant_id}/invitations",
            actual_path=f"/api/tenants/{self.ctx.enterprise_tenant_id}/invitations",
            token=self.ctx.owner_token,
            json={"email": self.ctx.member_email, "role": "viewer"},
        )
        self._assert_tenant_member_data(
            invited,
            tenant_id=self.ctx.enterprise_tenant_id,
            user_id=self.ctx.member_user_id,
            email=self.ctx.member_email,
            role="viewer",
            status="invited",
        )

        invitations = self.success("GET", "/api/tenants/invitations", token=self.ctx.member_token)
        assert isinstance(invitations, list)
        invite_item = _find_one(
            invitations,
            where="member invitations",
            tenant_id=self.ctx.enterprise_tenant_id,
        )
        assert invite_item["status"] == "invited"
        assert invite_item["role"] == "viewer"

        join_data = self.success(
            "POST",
            "/api/tenants/{tenant_id}/join",
            actual_path=f"/api/tenants/{self.ctx.enterprise_tenant_id}/join",
            token=self.ctx.member_token,
        )
        self._assert_tenant_member_data(
            join_data,
            tenant_id=self.ctx.enterprise_tenant_id,
            user_id=self.ctx.member_user_id,
            email=self.ctx.member_email,
            role="viewer",
            status="active",
        )

        # 再次加入应保持 active，不应报错。
        join_again_data = self.success(
            "POST",
            "/api/tenants/{tenant_id}/join",
            actual_path=f"/api/tenants/{self.ctx.enterprise_tenant_id}/join",
            token=self.ctx.member_token,
        )
        assert join_again_data["status"] == "active"

        switched = self.success(
            "POST",
            "/api/auth/switch-tenant",
            token=self.ctx.member_token,
            json={"tenant_id": self.ctx.enterprise_tenant_id},
        )
        self._assert_auth_login_data(switched, tenant_id=self.ctx.enterprise_tenant_id)
        self.ctx.member_token = switched["access_token"]

        member_me = self.success("GET", "/api/auth/me", token=self.ctx.member_token)
        self._assert_auth_me_data(
            member_me,
            expected_email=self.ctx.member_email,
            expected_user_id=self.ctx.member_user_id,
        )
        _find_one(member_me["tenants"], where="member me tenants", tenant_id=self.ctx.enterprise_tenant_id)

    def stage_permission_flow(self) -> None:
        self.stage("权限流程")
        # 目标：覆盖权限快照、配置目录、模板发布、角色权限变更与非法权限码负例。

        snapshot_before = self.success("GET", "/api/permissions/me", token=self.ctx.member_token)
        _require_keys(snapshot_before, ["tenant_role", "allowed_actions"], "permissions.me.before")
        assert snapshot_before["tenant_role"] == "viewer"
        assert isinstance(snapshot_before["allowed_actions"], list)

        # 在 viewer 权限下访问配置目录，应被禁止。
        forbidden_error = self.expect_error(
            "GET",
            "/api/permissions/catalog",
            token=self.ctx.member_token,
            expected_status=403,
            allow_stop=False,
        )
        assert forbidden_error["details"].get("reason")

        promoted = self.success(
            "PUT",
            "/api/tenants/{tenant_id}/members/{user_id}/role",
            actual_path=f"/api/tenants/{self.ctx.enterprise_tenant_id}/members/{self.ctx.member_user_id}/role",
            token=self.ctx.owner_token,
            json={"role": "admin"},
        )
        self._assert_tenant_member_data(
            promoted,
            tenant_id=self.ctx.enterprise_tenant_id,
            user_id=self.ctx.member_user_id,
            email=self.ctx.member_email,
            role="admin",
            status="active",
        )

        snapshot_after = self.success("GET", "/api/permissions/me", token=self.ctx.member_token)
        assert snapshot_after["tenant_role"] == "admin"
        assert isinstance(snapshot_after["allowed_actions"], list) and len(snapshot_after["allowed_actions"]) > 0

        catalog_data = self.success("GET", "/api/permissions/catalog", token=self.ctx.member_token)
        _require_keys(catalog_data, ["permission_codes"], "permissions.catalog.data")
        assert isinstance(catalog_data["permission_codes"], list) and len(catalog_data["permission_codes"]) > 0
        assert "api.tenant.read" in catalog_data["permission_codes"]

        template_data = self.success("GET", "/api/permissions/templates/default", token=self.ctx.member_token)
        _require_keys(template_data, ["template_key", "version", "catalog", "role_permissions"], "permissions.template.data")
        _assert_non_empty_str(template_data["template_key"], "permissions.template_key")
        _assert_non_empty_str(template_data["version"], "permissions.version")
        assert isinstance(template_data["catalog"], list) and len(template_data["catalog"]) > 0
        assert isinstance(template_data["role_permissions"], list) and len(template_data["role_permissions"]) > 0
        role_set = {item["role"] for item in template_data["role_permissions"]}
        assert {"owner", "admin", "member", "viewer"}.issubset(role_set)

        publish_data = self.success(
            "POST",
            "/api/permissions/templates/default/publish",
            token=self.ctx.member_token,
            json={"overwrite_existing": True},
        )
        _require_keys(
            publish_data,
            ["template_key", "version", "overwrite_existing", "role_permissions"],
            "permissions.publish.data",
        )
        assert publish_data["overwrite_existing"] is True
        assert isinstance(publish_data["role_permissions"], list) and len(publish_data["role_permissions"]) > 0

        roles_data = self.success("GET", "/api/permissions/roles", token=self.ctx.member_token)
        assert isinstance(roles_data, list) and len(roles_data) > 0
        viewer_role_before = _find_one(roles_data, where="roles list", role="viewer")
        self._assert_role_permission_data(viewer_role_before, role="viewer")

        updated_viewer = self.success(
            "PUT",
            "/api/permissions/roles/{role}",
            actual_path="/api/permissions/roles/viewer",
            token=self.ctx.member_token,
            json={"permission_codes": ["api.tenant.read", "menu.workspace"]},
        )
        self._assert_role_permission_data(
            updated_viewer,
            role="viewer",
            contains={"api.tenant.read", "menu.workspace"},
        )

        # 负例：不存在的权限码应触发 422。
        invalid_permission_error = self.expect_error(
            "PUT",
            "/api/permissions/roles/{role}",
            actual_path="/api/permissions/roles/viewer",
            token=self.ctx.member_token,
            expected_status=422,
            json={"permission_codes": ["api.invalid.code"]},
        )
        invalid_codes = invalid_permission_error["details"].get("invalid_codes")
        assert isinstance(invalid_codes, list) and "api.invalid.code" in invalid_codes

        reset_viewer = self.success(
            "DELETE",
            "/api/permissions/roles/{role}",
            actual_path="/api/permissions/roles/viewer",
            token=self.ctx.member_token,
        )
        self._assert_role_permission_data(reset_viewer, role="viewer")
        assert len(reset_viewer["permission_codes"]) > 0

    def stage_users_and_workspaces_flow(self) -> None:
        self.stage("用户与工作空间流程")
        # 目标：覆盖用户资料管理 + 工作空间及成员关系的增删改查。

        user3 = self.success(
            "POST",
            "/api/tenants/{tenant_id}/members",
            actual_path=f"/api/tenants/{self.ctx.enterprise_tenant_id}/members",
            token=self.ctx.owner_token,
            json={"email": self.ctx.user3_email, "role": "member"},
        )
        self.ctx.user3_id = user3["user_id"]
        self.trace("tenant-member-upserted", user_id=self.ctx.user3_id, email=self.ctx.user3_email, role="member")
        self._assert_tenant_member_data(
            user3,
            tenant_id=self.ctx.enterprise_tenant_id,
            user_id=self.ctx.user3_id,
            email=self.ctx.user3_email,
            role="member",
            status="active",
        )

        user4 = self.success(
            "POST",
            "/api/tenants/{tenant_id}/members",
            actual_path=f"/api/tenants/{self.ctx.enterprise_tenant_id}/members",
            token=self.ctx.owner_token,
            json={"email": self.ctx.user4_email, "role": "member"},
        )
        self.ctx.user4_id = user4["user_id"]
        self.trace("tenant-member-upserted", user_id=self.ctx.user4_id, email=self.ctx.user4_email, role="member")
        self._assert_tenant_member_data(
            user4,
            tenant_id=self.ctx.enterprise_tenant_id,
            user_id=self.ctx.user4_id,
            email=self.ctx.user4_email,
            role="member",
            status="active",
        )

        users_data = self.success("GET", "/api/users", token=self.ctx.owner_token)
        assert isinstance(users_data, list) and len(users_data) >= 4
        member_user_item = _find_one(users_data, where="users list", user_id=self.ctx.member_user_id)
        self._assert_user_data(member_user_item, user_id=self.ctx.member_user_id, email=self.ctx.member_email)

        member_user_detail = self.success(
            "GET",
            "/api/users/{user_id}",
            actual_path=f"/api/users/{self.ctx.member_user_id}",
            token=self.ctx.owner_token,
        )
        self._assert_user_data(
            member_user_detail,
            user_id=self.ctx.member_user_id,
            email=self.ctx.member_email,
        )

        member_user_updated = self.success(
            "PATCH",
            "/api/users/{user_id}",
            actual_path=f"/api/users/{self.ctx.member_user_id}",
            token=self.ctx.owner_token,
            json={"display_name": "Member Updated"},
        )
        self._assert_user_data(
            member_user_updated,
            user_id=self.ctx.member_user_id,
            display_name="Member Updated",
        )

        member_user_after_update = self.success(
            "GET",
            "/api/users/{user_id}",
            actual_path=f"/api/users/{self.ctx.member_user_id}",
            token=self.ctx.owner_token,
        )
        assert member_user_after_update["display_name"] == "Member Updated"

        ws1 = self.success(
            "POST",
            "/api/workspaces",
            token=self.ctx.owner_token,
            json={"name": "WS One", "slug": f"ws-{uuid4().hex[:8]}", "description": "ws1"},
        )
        self.ctx.ws1_id = ws1["id"]
        self.trace("workspace-created", workspace_id=self.ctx.ws1_id, name="WS One")
        self._assert_workspace_data(ws1, workspace_id=self.ctx.ws1_id, name="WS One", status="active", role="ws_owner")

        ws2 = self.success(
            "POST",
            "/api/workspaces",
            token=self.ctx.owner_token,
            json={"name": "WS Two", "slug": f"ws-{uuid4().hex[:8]}", "description": "ws2"},
        )
        self.ctx.ws2_id = ws2["id"]
        self.trace("workspace-created", workspace_id=self.ctx.ws2_id, name="WS Two")
        self._assert_workspace_data(ws2, workspace_id=self.ctx.ws2_id, name="WS Two", status="active", role="ws_owner")

        workspaces = self.success("GET", "/api/workspaces", token=self.ctx.owner_token)
        assert isinstance(workspaces, list)
        ws1_item = _find_one(workspaces, where="workspace list", id=self.ctx.ws1_id)
        ws2_item = _find_one(workspaces, where="workspace list", id=self.ctx.ws2_id)
        self._assert_workspace_data(ws1_item, workspace_id=self.ctx.ws1_id)
        self._assert_workspace_data(ws2_item, workspace_id=self.ctx.ws2_id)

        ws1_updated = self.success(
            "PATCH",
            "/api/workspaces/{workspace_id}",
            actual_path=f"/api/workspaces/{self.ctx.ws1_id}",
            token=self.ctx.owner_token,
            json={"name": "WS One Updated"},
        )
        self._assert_workspace_data(ws1_updated, workspace_id=self.ctx.ws1_id, name="WS One Updated")

        ws_members_before = self.success(
            "GET",
            "/api/workspaces/{workspace_id}/members",
            actual_path=f"/api/workspaces/{self.ctx.ws1_id}/members",
            token=self.ctx.owner_token,
        )
        assert isinstance(ws_members_before, list)
        owner_ws_member = _find_one(
            ws_members_before,
            where="workspace members before",
            user_id=self.ctx.owner_user_id,
        )
        self._assert_workspace_member_data(
            owner_ws_member,
            workspace_id=self.ctx.ws1_id,
            user_id=self.ctx.owner_user_id,
            role="ws_owner",
            status="active",
        )

        member_ws_upsert = self.success(
            "POST",
            "/api/workspaces/{workspace_id}/members",
            actual_path=f"/api/workspaces/{self.ctx.ws1_id}/members",
            token=self.ctx.owner_token,
            json={"user_id": self.ctx.member_user_id, "role": "ws_editor"},
        )
        self._assert_workspace_member_data(
            member_ws_upsert,
            workspace_id=self.ctx.ws1_id,
            user_id=self.ctx.member_user_id,
            role="ws_editor",
            status="active",
        )

        ws_members_after_upsert = self.success(
            "GET",
            "/api/workspaces/{workspace_id}/members",
            actual_path=f"/api/workspaces/{self.ctx.ws1_id}/members",
            token=self.ctx.owner_token,
        )
        updated_member_item = _find_one(
            ws_members_after_upsert,
            where="workspace members after upsert",
            user_id=self.ctx.member_user_id,
        )
        assert updated_member_item["role"] == "ws_editor"

        removed_ws_member = self.success(
            "DELETE",
            "/api/workspaces/{workspace_id}/members/{user_id}",
            actual_path=f"/api/workspaces/{self.ctx.ws1_id}/members/{self.ctx.user4_id}",
            token=self.ctx.owner_token,
        )
        self._assert_workspace_member_data(
            removed_ws_member,
            workspace_id=self.ctx.ws1_id,
            user_id=self.ctx.user4_id,
            status="disabled",
        )

        ws_members_after_remove = self.success(
            "GET",
            "/api/workspaces/{workspace_id}/members",
            actual_path=f"/api/workspaces/{self.ctx.ws1_id}/members",
            token=self.ctx.owner_token,
        )
        removed_member_item = _find_one(
            ws_members_after_remove,
            where="workspace members after remove",
            user_id=self.ctx.user4_id,
        )
        assert removed_member_item["status"] == "disabled"

        deleted_ws2 = self.success(
            "DELETE",
            "/api/workspaces/{workspace_id}",
            actual_path=f"/api/workspaces/{self.ctx.ws2_id}",
            token=self.ctx.owner_token,
        )
        self._assert_workspace_data(
            deleted_ws2,
            workspace_id=self.ctx.ws2_id,
            status="archived",
        )

        workspaces_after_delete = self.success("GET", "/api/workspaces", token=self.ctx.owner_token)
        assert not any(item["id"] == self.ctx.ws2_id for item in workspaces_after_delete)

    def stage_knowledge_base_and_documents_flow(self) -> None:
        self.stage("知识库与文档流程")
        # 目标：覆盖知识库成员与文档上传/更新/重建索引/删除的全生命周期。

        kb1 = self.success(
            "POST",
            "/api/knowledge-bases",
            token=self.ctx.owner_token,
            json={"workspace_id": self.ctx.ws1_id, "name": "KB One", "embedding_model": "text-embedding-3-large"},
        )
        self.ctx.kb1_id = kb1["id"]
        self.trace("kb-created", kb_id=self.ctx.kb1_id, name="KB One", workspace_id=self.ctx.ws1_id)
        self._assert_kb_data(
            kb1,
            kb_id=self.ctx.kb1_id,
            workspace_id=self.ctx.ws1_id,
            name="KB One",
            status="active",
        )

        kb2 = self.success(
            "POST",
            "/api/knowledge-bases",
            token=self.ctx.owner_token,
            json={"workspace_id": self.ctx.ws1_id, "name": "KB Two", "embedding_model": "text-embedding-3-large"},
        )
        self.ctx.kb2_id = kb2["id"]
        self.trace("kb-created", kb_id=self.ctx.kb2_id, name="KB Two", workspace_id=self.ctx.ws1_id)
        self._assert_kb_data(
            kb2,
            kb_id=self.ctx.kb2_id,
            workspace_id=self.ctx.ws1_id,
            name="KB Two",
            status="active",
        )

        kb_list = self.success("GET", "/api/knowledge-bases", token=self.ctx.owner_token)
        assert isinstance(kb_list, list)
        _find_one(kb_list, where="kb list", id=self.ctx.kb1_id)
        _find_one(kb_list, where="kb list", id=self.ctx.kb2_id)

        kb1_updated = self.success(
            "PATCH",
            "/api/knowledge-bases/{kb_id}",
            actual_path=f"/api/knowledge-bases/{self.ctx.kb1_id}",
            token=self.ctx.owner_token,
            json={"name": "KB One Updated"},
        )
        self._assert_kb_data(
            kb1_updated,
            kb_id=self.ctx.kb1_id,
            name="KB One Updated",
        )

        kb_members_before = self.success(
            "GET",
            "/api/knowledge-bases/{kb_id}/members",
            actual_path=f"/api/knowledge-bases/{self.ctx.kb1_id}/members",
            token=self.ctx.owner_token,
        )
        assert isinstance(kb_members_before, list)
        owner_kb_member = _find_one(
            kb_members_before,
            where="kb members before",
            user_id=self.ctx.owner_user_id,
        )
        self._assert_kb_member_data(
            owner_kb_member,
            kb_id=self.ctx.kb1_id,
            user_id=self.ctx.owner_user_id,
            role="kb_owner",
            status="active",
        )

        kb_member_upsert = self.success(
            "PUT",
            "/api/knowledge-bases/{kb_id}/members/{user_id}",
            actual_path=f"/api/knowledge-bases/{self.ctx.kb1_id}/members/{self.ctx.member_user_id}",
            token=self.ctx.owner_token,
            json={"role": "kb_editor"},
        )
        self._assert_kb_member_data(
            kb_member_upsert,
            kb_id=self.ctx.kb1_id,
            user_id=self.ctx.member_user_id,
            role="kb_editor",
            status="active",
        )

        kb_members_after_upsert = self.success(
            "GET",
            "/api/knowledge-bases/{kb_id}/members",
            actual_path=f"/api/knowledge-bases/{self.ctx.kb1_id}/members",
            token=self.ctx.owner_token,
        )
        updated_kb_member = _find_one(
            kb_members_after_upsert,
            where="kb members after upsert",
            user_id=self.ctx.member_user_id,
        )
        assert updated_kb_member["role"] == "kb_editor"

        kb_member_removed = self.success(
            "DELETE",
            "/api/knowledge-bases/{kb_id}/members/{user_id}",
            actual_path=f"/api/knowledge-bases/{self.ctx.kb1_id}/members/{self.ctx.member_user_id}",
            token=self.ctx.owner_token,
        )
        self._assert_kb_member_data(
            kb_member_removed,
            kb_id=self.ctx.kb1_id,
            user_id=self.ctx.member_user_id,
            role="kb_editor",
            status="disabled",
        )

        kb_members_after_remove = self.success(
            "GET",
            "/api/knowledge-bases/{kb_id}/members",
            actual_path=f"/api/knowledge-bases/{self.ctx.kb1_id}/members",
            token=self.ctx.owner_token,
        )
        removed_kb_member_item = _find_one(
            kb_members_after_remove,
            where="kb members after remove",
            user_id=self.ctx.member_user_id,
        )
        assert removed_kb_member_item["status"] == "disabled"

        kb2_deleted = self.success(
            "DELETE",
            "/api/knowledge-bases/{kb_id}",
            actual_path=f"/api/knowledge-bases/{self.ctx.kb2_id}",
            token=self.ctx.owner_token,
        )
        self._assert_kb_data(kb2_deleted, kb_id=self.ctx.kb2_id, status="archived")

        kb_list_after_delete = self.success("GET", "/api/knowledge-bases", token=self.ctx.owner_token)
        assert not any(item["id"] == self.ctx.kb2_id for item in kb_list_after_delete)

        upload_data = self.success(
            "POST",
            "/api/knowledge-bases/{kb_id}/documents",
            actual_path=f"/api/knowledge-bases/{self.ctx.kb1_id}/documents",
            token=self.ctx.owner_token,
            headers={"Idempotency-Key": f"upload-{uuid4().hex}"},
            files={"file": ("guide.txt", b"hello world", "text/plain")},
            data={"metadata": json.dumps({"lang": "zh"})},
        )
        _require_keys(
            upload_data,
            ["document_id", "workspace_id", "document_version_id", "version", "status", "job_id", "job_status"],
            "document.upload.data",
        )
        self.ctx.document_id = upload_data["document_id"]
        self.trace(
            "document-uploaded",
            document_id=self.ctx.document_id,
            workspace_id=upload_data["workspace_id"],
            job_id=upload_data["job_id"],
        )
        _assert_uuid(upload_data["document_id"], "document.upload.document_id")
        _assert_uuid(upload_data["workspace_id"], "document.upload.workspace_id")
        _assert_uuid(upload_data["document_version_id"], "document.upload.document_version_id")
        _assert_uuid(upload_data["job_id"], "document.upload.job_id")
        assert upload_data["workspace_id"] == self.ctx.ws1_id
        assert isinstance(upload_data["version"], int) and upload_data["version"] >= 1
        _assert_non_empty_str(upload_data["status"], "document.upload.status")
        _assert_non_empty_str(upload_data["job_status"], "document.upload.job_status")

        docs_list = self.success(
            "GET",
            "/api/knowledge-bases/{kb_id}/documents",
            actual_path=f"/api/knowledge-bases/{self.ctx.kb1_id}/documents",
            token=self.ctx.owner_token,
        )
        assert isinstance(docs_list, list)
        doc_item = _find_one(docs_list, where="documents list", id=self.ctx.document_id)
        self._assert_document_data(
            doc_item,
            document_id=self.ctx.document_id,
            kb_id=self.ctx.kb1_id,
            workspace_id=self.ctx.ws1_id,
        )

        doc_detail = self.success(
            "GET",
            "/api/documents/{document_id}",
            actual_path=f"/api/documents/{self.ctx.document_id}",
            token=self.ctx.owner_token,
        )
        self._assert_document_data(
            doc_detail,
            document_id=self.ctx.document_id,
            kb_id=self.ctx.kb1_id,
            workspace_id=self.ctx.ws1_id,
        )

        updated_doc = self.success(
            "PATCH",
            "/api/documents/{document_id}",
            actual_path=f"/api/documents/{self.ctx.document_id}",
            token=self.ctx.owner_token,
            json={"title": "Guide Updated", "metadata": {"lang": "zh", "tag": "t1"}},
        )
        self._assert_document_data(
            updated_doc,
            document_id=self.ctx.document_id,
            title="Guide Updated",
        )
        assert updated_doc["metadata"] == {"lang": "zh", "tag": "t1"}

        doc_after_update = self.success(
            "GET",
            "/api/documents/{document_id}",
            actual_path=f"/api/documents/{self.ctx.document_id}",
            token=self.ctx.owner_token,
        )
        assert doc_after_update["title"] == "Guide Updated"
        assert doc_after_update["metadata"] == {"lang": "zh", "tag": "t1"}

        reindex_data = self.success(
            "POST",
            "/api/documents/{document_id}/reindex",
            actual_path=f"/api/documents/{self.ctx.document_id}/reindex",
            token=self.ctx.owner_token,
            headers={"Idempotency-Key": f"reindex-{uuid4().hex}"},
        )
        _require_keys(reindex_data, ["job_id", "status"], "document.reindex.data")
        _assert_uuid(reindex_data["job_id"], "document.reindex.job_id")
        _assert_non_empty_str(reindex_data["status"], "document.reindex.status")

        job_detail = self.success(
            "GET",
            "/api/ingestion-jobs/{job_id}",
            actual_path=f"/api/ingestion-jobs/{reindex_data['job_id']}",
            token=self.ctx.owner_token,
        )
        _require_keys(
            job_detail,
            [
                "job_id",
                "workspace_id",
                "document_id",
                "document_version_id",
                "status",
                "stage",
                "progress",
                "attempt_count",
                "max_attempts",
                "next_run_at",
                "locked_at",
                "locked_by",
                "heartbeat_at",
                "started_at",
                "finished_at",
                "error",
                "terminal",
            ],
            "ingestion.job.data",
        )
        assert job_detail["job_id"] == reindex_data["job_id"]
        assert job_detail["workspace_id"] == self.ctx.ws1_id
        assert job_detail["document_id"] == self.ctx.document_id
        _assert_uuid(job_detail["document_version_id"], "ingestion.document_version_id")
        _assert_non_empty_str(job_detail["status"], "ingestion.status")
        _assert_non_empty_str(job_detail["stage"], "ingestion.stage")
        assert isinstance(job_detail["progress"], int) and 0 <= job_detail["progress"] <= 100
        assert isinstance(job_detail["attempt_count"], int) and job_detail["attempt_count"] >= 0
        assert isinstance(job_detail["max_attempts"], int) and job_detail["max_attempts"] >= 1
        _assert_iso_datetime(job_detail["next_run_at"], "ingestion.next_run_at")
        if job_detail["locked_at"] is not None:
            _assert_iso_datetime(job_detail["locked_at"], "ingestion.locked_at")
        if job_detail["heartbeat_at"] is not None:
            _assert_iso_datetime(job_detail["heartbeat_at"], "ingestion.heartbeat_at")
        if job_detail["started_at"] is not None:
            _assert_iso_datetime(job_detail["started_at"], "ingestion.started_at")
        if job_detail["finished_at"] is not None:
            _assert_iso_datetime(job_detail["finished_at"], "ingestion.finished_at")
        assert job_detail["locked_by"] is None or isinstance(job_detail["locked_by"], str)
        assert job_detail["error"] is None or isinstance(job_detail["error"], str)
        assert isinstance(job_detail["terminal"], bool)

        deleted_doc = self.success(
            "DELETE",
            "/api/documents/{document_id}",
            actual_path=f"/api/documents/{self.ctx.document_id}",
            token=self.ctx.owner_token,
        )
        self._assert_document_data(
            deleted_doc,
            document_id=self.ctx.document_id,
            kb_id=self.ctx.kb1_id,
            workspace_id=self.ctx.ws1_id,
            status="deleted",
        )

        docs_after_delete = self.success(
            "GET",
            "/api/knowledge-bases/{kb_id}/documents",
            actual_path=f"/api/knowledge-bases/{self.ctx.kb1_id}/documents",
            token=self.ctx.owner_token,
        )
        assert not any(item["id"] == self.ctx.document_id for item in docs_after_delete)

    def stage_cleanup_and_logout(self) -> None:
        self.stage("资源清理与登出")
        # 目标：验证清理动作与登出后 token 失效行为。

        removed_user3 = self.success(
            "DELETE",
            "/api/users/{user_id}",
            actual_path=f"/api/users/{self.ctx.user3_id}",
            token=self.ctx.owner_token,
        )
        self._assert_user_data(
            removed_user3,
            user_id=self.ctx.user3_id,
            email=self.ctx.user3_email,
            membership_status="disabled",
        )

        users_after_remove = self.success("GET", "/api/users", token=self.ctx.owner_token)
        user3_after_remove = _find_one(users_after_remove, where="users after remove", user_id=self.ctx.user3_id)
        assert user3_after_remove["membership_status"] == "disabled"

        removed_user4_from_tenant = self.success(
            "DELETE",
            "/api/tenants/{tenant_id}/members/{user_id}",
            actual_path=f"/api/tenants/{self.ctx.enterprise_tenant_id}/members/{self.ctx.user4_id}",
            token=self.ctx.owner_token,
        )
        self._assert_tenant_member_data(
            removed_user4_from_tenant,
            tenant_id=self.ctx.enterprise_tenant_id,
            user_id=self.ctx.user4_id,
            email=self.ctx.user4_email,
            status="disabled",
        )

        temp_tenant = self.success(
            "POST",
            "/api/tenants",
            token=self.ctx.owner_token,
            json={"name": "Temp Tenant", "slug": f"temp-{uuid4().hex[:8]}"},
        )
        _require_keys(temp_tenant, ["tenant_id", "name", "slug", "role", "default_workspace_id"], "temp tenant")
        temp_tenant_id = temp_tenant["tenant_id"]

        switched = self.success(
            "POST",
            "/api/auth/switch-tenant",
            token=self.ctx.owner_token,
            json={"tenant_id": temp_tenant_id},
        )
        self._assert_auth_login_data(switched, tenant_id=temp_tenant_id)
        self.ctx.owner_token = switched["access_token"]

        deleted_temp_tenant = self.success(
            "DELETE",
            "/api/tenants/{tenant_id}",
            actual_path=f"/api/tenants/{temp_tenant_id}",
            token=self.ctx.owner_token,
        )
        self._assert_tenant_data(
            deleted_temp_tenant,
            tenant_id=temp_tenant_id,
            status="deleted",
            role="owner",
        )

        logout_data = self.success("POST", "/api/auth/logout", token=self.ctx.member_token)
        _require_keys(logout_data, ["logged_out", "revoked"], "auth.logout.data")
        assert logout_data["logged_out"] is True
        assert isinstance(logout_data["revoked"], bool)

        me_after_logout_error = self.expect_error(
            "GET",
            "/api/auth/me",
            token=self.ctx.member_token,
            expected_status=401,
        )
        assert me_after_logout_error["code"]


def _reset_runtime_auth_state() -> None:
    security_module._redis_client = None
    security_module._LOCAL_BLACKLIST.clear()
    security_module._LOCAL_ACTIVE_USER_SESSIONS.clear()
    security_module._LOCAL_ACTIVE_JTI_SESSIONS.clear()


def _truncate_all_tables_for_test(db_engine) -> None:
    table_names = [table.name for table in Base.metadata.sorted_tables]
    if not table_names:
        return
    with db_engine.begin() as conn:
        if db_engine.dialect.name == "postgresql":
            quoted_tables = ", ".join(f'"{name}"' for name in table_names)
            conn.exec_driver_sql(f"TRUNCATE TABLE {quoted_tables}")
            return
        for name in reversed(table_names):
            conn.exec_driver_sql(f'DELETE FROM "{name}"')


@pytest.fixture
def api_client(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Generator[TestClient, None, None]:
    monkeypatch.setenv("KD_AUTH_JWT_SECRET", "http-test-secret-key-at-least-32-bytes")
    monkeypatch.setenv("KD_AUTH_JWT_ALGORITHMS", "HS256")
    monkeypatch.setenv("KD_STORAGE_ROOT", str(tmp_path / "storage"))
    get_settings.cache_clear()
    _reset_runtime_auth_state()
    app.dependency_overrides.clear()

    db_mode = os.getenv("TKP_TEST_DB_MODE", "sqlite").strip().lower()
    if db_mode == "postgres":
        _truncate_all_tables_for_test(app_engine)
        with TestClient(app) as client:
            yield client
        _truncate_all_tables_for_test(app_engine)
        _reset_runtime_auth_state()
        get_settings.cache_clear()
        return

    sqlite_engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    testing_session_local = sessionmaker(bind=sqlite_engine, autoflush=False, autocommit=False, class_=Session)
    Base.metadata.create_all(bind=sqlite_engine)

    def override_get_db() -> Generator[Session, None, None]:
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=sqlite_engine)
    _reset_runtime_auth_state()
    get_settings.cache_clear()


def _is_log_enabled() -> bool:
    return os.getenv("TKP_TEST_LOG", "1").strip() not in {"0", "false", "False"}


def _log(message: str) -> None:
    if _is_log_enabled():
        print(message)


def _all_http_openapi_endpoints() -> list[tuple[str, str]]:
    return sorted(
        {
            (method.upper(), path)
            for path, operations in app.openapi()["paths"].items()
            for method in operations.keys()
            if method in {"get", "post", "put", "patch", "delete"}
        }
    )


def _single_case_id(case: tuple[str, str]) -> str:
    method, path = case
    slug = path.strip("/").replace("/", "__").replace("{", "").replace("}", "").replace("-", "_")
    return f"{method.lower()}__{slug}"


def _run_workflow(
    api_client: TestClient,
    *,
    stop_at: tuple[str, str] | None = None,
    check_coverage: bool = True,
) -> None:
    _log(
        f"[RUN] workflow-start | stop_at={stop_at} | check_coverage={check_coverage} "
        f"| verbose={_is_verbose_log_enabled()} | payload={_is_payload_log_enabled()}"
    )
    runner = WorkflowRunner(api_client, stop_at=stop_at)
    runner.run()

    if stop_at:
        assert runner.stop_hit, f"单接口目标未命中：{stop_at[0]} {stop_at[1]}"
        _log(f"[DONE] 单接口模式完成，耗时 {runner.elapsed():.2f}s")
        return

    if check_coverage:
        expected = set(_all_http_openapi_endpoints())
        missing = sorted(expected - runner.covered)
        assert not missing, f"missing route coverage: {missing}"

    _log(f"[DONE] 全流程完成，覆盖 {len(runner.covered)} 个接口，耗时 {runner.elapsed():.2f}s")


@pytest.mark.smoke
def test_http_api_smoke_core_auth_and_health(api_client: TestClient):
    """冒烟测试：核心认证链路 + 健康检查，适合日常快速回归。"""
    runner = WorkflowRunner(api_client)
    runner.stage_auth_and_health()

    runner.stage("Smoke 收尾")
    logout_data = runner.success("POST", "/api/auth/logout", token=runner.ctx.owner_token)
    _require_keys(logout_data, ["logged_out", "revoked"], "smoke.auth.logout.data")
    assert logout_data["logged_out"] is True
    assert isinstance(logout_data["revoked"], bool)

    runner.expect_error(
        "GET",
        "/api/auth/me",
        token=runner.ctx.owner_token,
        expected_status=401,
    )
    runner._finish_current_stage()
    _log(f"[DONE] smoke 流程完成，耗时 {runner.elapsed():.2f}s")


@pytest.mark.permissions_matrix
def test_http_api_permissions_config_matrix_by_role(api_client: TestClient):
    """
    权限专项：验证同一组权限配置接口在不同角色下的访问矩阵。
    场景：viewer 应 403，提升为 admin 后应 200。
    """
    runner = WorkflowRunner(api_client)
    runner.stage_auth_and_health()
    runner.stage_tenant_flow()
    runner.stage_member_join_flow()

    runner.stage("权限矩阵专项")
    viewer_token = runner.ctx.member_token
    owner_token = runner.ctx.owner_token
    tenant_id = runner.ctx.enterprise_tenant_id
    member_user_id = runner.ctx.member_user_id

    restricted_endpoints = [
        ("GET", "/api/permissions/catalog"),
        ("GET", "/api/permissions/templates/default"),
        ("GET", "/api/permissions/roles"),
    ]
    for method, path in restricted_endpoints:
        runner.expect_error(method, path, token=viewer_token, expected_status=403)

    promoted = runner.success(
        "PUT",
        "/api/tenants/{tenant_id}/members/{user_id}/role",
        actual_path=f"/api/tenants/{tenant_id}/members/{member_user_id}/role",
        token=owner_token,
        json={"role": "admin"},
    )
    runner._assert_tenant_member_data(
        promoted,
        tenant_id=tenant_id,
        user_id=member_user_id,
        email=runner.ctx.member_email,
        role="admin",
        status="active",
    )

    snapshot = runner.success("GET", "/api/permissions/me", token=viewer_token)
    _require_keys(snapshot, ["tenant_role", "allowed_actions"], "permissions.matrix.snapshot")
    assert snapshot["tenant_role"] == "admin"
    assert isinstance(snapshot["allowed_actions"], list) and len(snapshot["allowed_actions"]) > 0

    catalog = runner.success("GET", "/api/permissions/catalog", token=viewer_token)
    _require_keys(catalog, ["permission_codes"], "permissions.matrix.catalog")
    assert isinstance(catalog["permission_codes"], list) and len(catalog["permission_codes"]) > 0

    template = runner.success("GET", "/api/permissions/templates/default", token=viewer_token)
    _require_keys(template, ["template_key", "version", "catalog", "role_permissions"], "permissions.matrix.template")
    assert isinstance(template["role_permissions"], list) and len(template["role_permissions"]) > 0

    roles = runner.success("GET", "/api/permissions/roles", token=viewer_token)
    assert isinstance(roles, list) and len(roles) > 0
    _find_one(roles, where="permissions.matrix.roles", role="admin")
    _find_one(roles, where="permissions.matrix.roles", role="viewer")

    runner._finish_current_stage()
    _log(f"[DONE] permissions-matrix 完成，耗时 {runner.elapsed():.2f}s")


@pytest.mark.full
def test_http_api_full_workflow_with_permissions_and_coverage(api_client: TestClient):
    """全量强校验：发版前执行，覆盖所有 HTTP 接口与核心负例。"""
    _run_workflow(api_client, check_coverage=True)


@pytest.mark.parametrize(
    "single_endpoint",
    _all_http_openapi_endpoints(),
    ids=_single_case_id,
)
@pytest.mark.full
def test_http_api_single_endpoint_case(api_client: TestClient, single_endpoint: tuple[str, str]):
    """单接口测试入口（IDE/命令行可像 JUnit 方法一样点选执行）。"""
    _run_workflow(api_client, stop_at=single_endpoint, check_coverage=False)
