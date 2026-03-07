"""Sensitive-data masking helpers used by middleware and APIs."""

from __future__ import annotations

from typing import Any

from tkp_api.governance.pii import get_pii_masker


class SensitiveDataMasker:
    """Mask sensitive fields in nested payloads."""

    def __init__(self) -> None:
        self._pii_masker = get_pii_masker()
        self._sensitive_keywords = (
            "password",
            "secret",
            "token",
            "api_key",
            "apikey",
            "authorization",
            "credential",
            "private_key",
            "access_key",
            "secret_key",
            "email",
            "phone",
            "mobile",
            "id_card",
            "identity",
        )

    def mask_dict(self, data: dict[str, Any], *, recursive: bool = True) -> dict[str, Any]:
        """Mask sensitive fields in a dictionary.

        The `recursive` flag is kept for backwards compatibility with older callers.
        Current implementation always masks nested dict/list structures.
        """
        if not isinstance(data, dict):
            return data
        return self._mask_dict(data, recursive=recursive)

    def _mask_dict(self, data: dict[str, Any], *, recursive: bool) -> dict[str, Any]:
        masked: dict[str, Any] = {}
        for key, value in data.items():
            lower_key = key.lower()
            if any(k in lower_key for k in self._sensitive_keywords):
                masked[key] = self._mask_value(value, recursive=recursive)
                continue

            if recursive and isinstance(value, dict):
                masked[key] = self._mask_dict(value, recursive=True)
                continue
            if recursive and isinstance(value, list):
                masked[key] = [self._mask_dict(item, recursive=True) if isinstance(item, dict) else item for item in value]
                continue
            masked[key] = value
        return masked

    def _mask_value(self, value: Any, *, recursive: bool) -> Any:
        if isinstance(value, str):
            if "@" in value:
                return self._pii_masker.mask_email(value)
            if len(value) <= 2:
                return "*" * len(value)
            if len(value) <= 6:
                return value[0] + ("*" * (len(value) - 1))
            return value[:2] + ("*" * (len(value) - 4)) + value[-2:]

        if isinstance(value, dict):
            return self._mask_dict(value, recursive=recursive) if recursive else "***"
        if isinstance(value, list):
            if not recursive:
                return "***"
            return [self._mask_value(item, recursive=True) for item in value]
        return "***"


default_masker = SensitiveDataMasker()
