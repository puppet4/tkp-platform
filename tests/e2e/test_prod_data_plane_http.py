from __future__ import annotations

import json
import os
import time
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
from sqlalchemy import create_engine, text


API_BASE_URL = os.getenv("TKP_E2E_API_BASE_URL", "http://127.0.0.1:18000")
DB_URL = os.getenv("TKP_E2E_DATABASE_URL")
MINIO_ENDPOINT = os.getenv("TKP_E2E_MINIO_ENDPOINT")
MINIO_ACCESS_KEY = os.getenv("TKP_E2E_MINIO_ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("TKP_E2E_MINIO_SECRET_KEY")
MINIO_BUCKET = os.getenv("TKP_E2E_MINIO_BUCKET", "tkp-documents")
MINIO_SECURE = os.getenv("TKP_E2E_MINIO_SECURE", "0").strip().lower() in {"1", "true", "yes"}


def _assert_iso(ts: str) -> None:
    datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _assert_success_envelope(payload: dict[str, Any], *, method: str, path: str) -> dict[str, Any]:
    assert isinstance(payload, dict)
    assert "request_id" in payload
    assert "data" in payload
    assert "meta" in payload
    assert isinstance(payload["request_id"], str) and payload["request_id"].strip()

    meta = payload["meta"]
    assert isinstance(meta, dict)
    assert meta["method"] == method.upper()
    assert meta["path"] == path
    _assert_iso(meta["timestamp"])
    assert isinstance(meta["message"], str) and meta["message"].strip()
    process_ms = meta.get("process_ms")
    assert process_ms is None or (isinstance(process_ms, int) and process_ms >= 0)
    return payload["data"]


def _api_success(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    token: str | None = None,
    expected_status: int = 200,
    **kwargs: Any,
) -> dict[str, Any]:
    headers = dict(kwargs.pop("headers", {}) or {})
    if token:
        headers["Authorization"] = f"Bearer {token}"

    resp = client.request(method, path, headers=headers, **kwargs)
    assert resp.status_code == expected_status, f"{method} {path} -> {resp.status_code}: {resp.text}"
    return _assert_success_envelope(resp.json(), method=method, path=path)


def _poll_job_until_done(client: httpx.Client, job_id: str, token: str, *, timeout_s: float = 90.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        data = _api_success(client, "GET", f"/api/ingestion-jobs/{job_id}", token=token)
        if data["status"] in {"completed", "dead_letter"}:
            return data
        time.sleep(1.0)
    raise AssertionError(f"job {job_id} not terminal within {timeout_s}s")


def _poll_retrieval_hits(
    client: httpx.Client,
    *,
    token: str,
    kb_id: str,
    query: str,
    timeout_s: float = 30.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    last_data: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        last_data = _api_success(
            client,
            "POST",
            "/api/retrieval/query",
            token=token,
            json={
                "query": query,
                "kb_ids": [kb_id],
                "top_k": 5,
                "filters": {"lang": "zh", "topic": "refund"},
                "with_citations": True,
            },
        )
        if last_data["hits"]:
            return last_data
        time.sleep(1.0)
    raise AssertionError(f"retrieval still empty after {timeout_s}s, last={last_data}")


def _assert_object_exists_in_minio(*, object_key: str) -> None:
    if not (MINIO_ENDPOINT and MINIO_ACCESS_KEY and MINIO_SECRET_KEY):
        return

    from minio import Minio

    client = Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=MINIO_SECURE,
    )
    stat = client.stat_object(MINIO_BUCKET, object_key)
    assert stat.size > 0


def _assert_embeddings_written(*, document_id: str) -> None:
    if not DB_URL:
        return

    engine = create_engine(DB_URL, future=True)
    with engine.connect() as conn:
        count = conn.execute(
            text(
                """
                SELECT count(*)
                FROM chunk_embeddings e
                JOIN document_chunks c ON c.id = e.chunk_id
                WHERE c.document_id = CAST(:document_id AS uuid)
                """
            ),
            {"document_id": document_id},
        ).scalar_one()
    assert isinstance(count, int) and count > 0


def test_prod_data_plane_end_to_end_http() -> None:
    user_email = f"e2e-{uuid4().hex[:10]}@example.com"
    password = "StrongPassw0rd!"
    display_name = "e2e-owner"

    with httpx.Client(base_url=API_BASE_URL, timeout=20.0, trust_env=False) as client:
        register_data = _api_success(
            client,
            "POST",
            "/api/auth/register",
            json={"email": user_email, "password": password, "display_name": display_name},
        )
        assert register_data["email"] == user_email
        assert register_data["display_name"] == display_name
        assert register_data["auth_provider"] == "local"
        UUID(register_data["user_id"])
        UUID(register_data["personal_tenant_id"])
        UUID(register_data["default_workspace_id"])

        login_data = _api_success(
            client,
            "POST",
            "/api/auth/login",
            json={"email": user_email, "password": password},
        )
        token = login_data["access_token"]
        assert login_data["token_type"] == "bearer"
        assert isinstance(login_data["expires_in"], int) and login_data["expires_in"] > 0
        assert login_data["tenant_id"] == register_data["personal_tenant_id"]

        me_data = _api_success(client, "GET", "/api/auth/me", token=token)
        assert me_data["user"]["email"] == user_email
        workspace_ids = {item["workspace_id"] for item in me_data["workspaces"]}
        assert register_data["default_workspace_id"] in workspace_ids

        kb_data = _api_success(
            client,
            "POST",
            "/api/knowledge-bases",
            token=token,
                json={
                    "workspace_id": register_data["default_workspace_id"],
                    "name": f"E2E KB {uuid4().hex[:6]}",
                    "description": "prod-like data plane e2e",
                    "embedding_model": "local-hash-1536",
                    "retrieval_strategy": {"mode": "hybrid"},
                },
            )
        kb_id = kb_data["id"]
        UUID(kb_id)

        upload_data = _api_success(
            client,
            "POST",
            f"/api/knowledge-bases/{kb_id}/documents",
            token=token,
            headers={"Idempotency-Key": f"e2e-upload-{uuid4().hex}"},
            files={"file": ("refund-guide.txt", "退款流程：先提交工单，再由财务审核，最后原路退回。".encode("utf-8"), "text/plain")},
            data={"metadata": json.dumps({"lang": "zh", "topic": "refund"}, ensure_ascii=False)},
        )

        document_id = upload_data["document_id"]
        job_id = upload_data["job_id"]
        UUID(document_id)
        UUID(job_id)

        job_data = _poll_job_until_done(client, job_id, token)
        assert job_data["status"] == "completed", f"ingestion failed: {job_data}"
        assert job_data["terminal"] is True
        assert isinstance(job_data["attempt_count"], int) and job_data["attempt_count"] >= 1

        chunks_data = _api_success(
            client,
            "GET",
            f"/api/documents/{document_id}/chunks",
            token=token,
            params={"version": upload_data["version"], "offset": 0, "limit": 20},
        )
        assert chunks_data["total"] >= 1
        assert len(chunks_data["items"]) >= 1
        assert chunks_data["document_id"] == document_id

        stats_data = _api_success(client, "GET", f"/api/knowledge-bases/{kb_id}/stats", token=token)
        assert stats_data["document_total"] >= 1
        assert stats_data["document_ready"] >= 1
        assert stats_data["chunk_total"] >= 1
        assert stats_data["job_total"] >= 1
        assert stats_data["job_completed"] >= 1

        retrieval_data = _poll_retrieval_hits(client, token=token, kb_id=kb_id, query="退款流程是什么")
        assert retrieval_data["latency_ms"] >= 0
        assert len(retrieval_data["hits"]) >= 1
        first_hit = retrieval_data["hits"][0]
        assert first_hit["document_id"] == document_id
        assert first_hit["kb_id"] == kb_id
        assert isinstance(first_hit["snippet"], str) and first_hit["snippet"].strip()
        assert first_hit["citation"] is not None

        chat_data = _api_success(
            client,
            "POST",
            "/api/chat/completions",
            token=token,
            json={
                "kb_ids": [kb_id],
                "messages": [{"role": "user", "content": "请说明退款流程并给出处。"}],
                "generation": {"temperature": 0.2, "max_tokens": 300},
            },
        )
        assert isinstance(chat_data["answer"], str) and chat_data["answer"].strip()
        assert isinstance(chat_data["citations"], list) and len(chat_data["citations"]) >= 1
        assert chat_data["conversation_id"]
        usage = chat_data["usage"]
        assert usage["total_tokens"] >= usage["prompt_tokens"] >= 1
        assert usage["completion_tokens"] >= 1

        version_rows = _api_success(client, "GET", f"/api/documents/{document_id}/versions", token=token)
        assert len(version_rows) >= 1
        current_version = max(item["version"] for item in version_rows)
        version_data = _api_success(
            client,
            "GET",
            f"/api/documents/{document_id}/versions/{current_version}",
            token=token,
        )
        assert isinstance(version_data["object_key"], str) and version_data["object_key"].strip()

        _assert_embeddings_written(document_id=document_id)
        _assert_object_exists_in_minio(object_key=version_data["object_key"])
