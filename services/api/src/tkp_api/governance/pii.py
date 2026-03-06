"""PII（个人身份信息）检测和脱敏模块。

支持检测和脱敏常见的敏感信息：邮箱、手机号、身份证号、银行卡号等。
"""

import logging
import re
from typing import Any

logger = logging.getLogger("tkp_api.governance.pii")


class PIIDetector:
    """PII 检测器。"""

    def __init__(self):
        """初始化 PII 检测器。"""
        # 正则表达式模式
        self.patterns = {
            "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
            "phone_cn": re.compile(r"\b1[3-9]\d{9}\b"),
            "id_card_cn": re.compile(r"\b\d{17}[\dXx]\b"),
            "credit_card": re.compile(r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b"),
            "ip_address": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
            "ssn_us": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        }

    def detect(self, text: str) -> dict[str, list[str]]:
        """检测文本中的 PII。

        Args:
            text: 待检测文本

        Returns:
            包含各类 PII 及其匹配结果的字典
        """
        if not text:
            return {}

        results = {}
        for pii_type, pattern in self.patterns.items():
            matches = pattern.findall(text)
            if matches:
                results[pii_type] = matches

        return results

    def has_pii(self, text: str) -> bool:
        """检查文本是否包含 PII。"""
        return bool(self.detect(text))


class PIIMasker:
    """PII 脱敏器。"""

    def __init__(self, mask_char: str = "*"):
        """初始化 PII 脱敏器。

        Args:
            mask_char: 脱敏字符
        """
        self.mask_char = mask_char
        self.detector = PIIDetector()

    def mask_email(self, email: str) -> str:
        """脱敏邮箱地址。

        示例: user@example.com -> u***@example.com
        """
        if "@" not in email:
            return email

        local, domain = email.split("@", 1)
        if len(local) <= 2:
            masked_local = self.mask_char * len(local)
        else:
            masked_local = local[0] + self.mask_char * (len(local) - 2) + local[-1]

        return f"{masked_local}@{domain}"

    def mask_phone(self, phone: str) -> str:
        """脱敏手机号。

        示例: 13812345678 -> 138****5678
        """
        if len(phone) != 11:
            return self.mask_char * len(phone)

        return phone[:3] + self.mask_char * 4 + phone[-4:]

    def mask_id_card(self, id_card: str) -> str:
        """脱敏身份证号。

        示例: 110101199001011234 -> 110101********1234
        """
        if len(id_card) != 18:
            return self.mask_char * len(id_card)

        return id_card[:6] + self.mask_char * 8 + id_card[-4:]

    def mask_credit_card(self, card: str) -> str:
        """脱敏银行卡号。

        示例: 6222 0000 0000 0000 -> 6222 **** **** 0000
        """
        # 移除空格和连字符
        digits = re.sub(r"[- ]", "", card)

        if len(digits) < 8:
            return self.mask_char * len(digits)

        masked = digits[:4] + self.mask_char * (len(digits) - 8) + digits[-4:]

        # 恢复原始格式
        if " " in card:
            return " ".join([masked[i : i + 4] for i in range(0, len(masked), 4)])
        elif "-" in card:
            return "-".join([masked[i : i + 4] for i in range(0, len(masked), 4)])

        return masked

    def mask_ip_address(self, ip: str) -> str:
        """脱敏 IP 地址。

        示例: 192.168.1.100 -> 192.168.***.***
        """
        parts = ip.split(".")
        if len(parts) != 4:
            return ip

        return f"{parts[0]}.{parts[1]}.{self.mask_char * 3}.{self.mask_char * 3}"

    def mask_text(self, text: str, pii_types: list[str] | None = None) -> str:
        """脱敏文本中的 PII。

        Args:
            text: 待脱敏文本
            pii_types: 要脱敏的 PII 类型列表（None 表示全部）

        Returns:
            脱敏后的文本
        """
        if not text:
            return text

        masked_text = text

        # 检测 PII
        detected = self.detector.detect(text)

        # 脱敏各类 PII
        for pii_type, matches in detected.items():
            if pii_types and pii_type not in pii_types:
                continue

            for match in matches:
                if pii_type == "email":
                    replacement = self.mask_email(match)
                elif pii_type == "phone_cn":
                    replacement = self.mask_phone(match)
                elif pii_type == "id_card_cn":
                    replacement = self.mask_id_card(match)
                elif pii_type == "credit_card":
                    replacement = self.mask_credit_card(match)
                elif pii_type == "ip_address":
                    replacement = self.mask_ip_address(match)
                else:
                    replacement = self.mask_char * len(match)

                masked_text = masked_text.replace(match, replacement)

        return masked_text

    def mask_dict(self, data: dict[str, Any], fields: list[str] | None = None) -> dict[str, Any]:
        """脱敏字典中的敏感字段。

        Args:
            data: 待脱敏字典
            fields: 要脱敏的字段列表（None 表示自动检测）

        Returns:
            脱敏后的字典
        """
        masked_data = data.copy()

        # 默认敏感字段
        sensitive_fields = fields or [
            "email",
            "phone",
            "mobile",
            "id_card",
            "identity",
            "password",
            "secret",
            "token",
            "api_key",
        ]

        for key, value in masked_data.items():
            if isinstance(value, str):
                # 检查字段名是否包含敏感关键词
                if any(field in key.lower() for field in sensitive_fields):
                    masked_data[key] = self.mask_text(value)
            elif isinstance(value, dict):
                masked_data[key] = self.mask_dict(value, fields)
            elif isinstance(value, list):
                masked_data[key] = [
                    self.mask_dict(item, fields) if isinstance(item, dict) else item for item in value
                ]

        return masked_data


# 全局实例
_pii_detector = None
_pii_masker = None


def get_pii_detector() -> PIIDetector:
    """获取全局 PII 检测器实例。"""
    global _pii_detector
    if _pii_detector is None:
        _pii_detector = PIIDetector()
    return _pii_detector


def get_pii_masker() -> PIIMasker:
    """获取全局 PII 脱敏器实例。"""
    global _pii_masker
    if _pii_masker is None:
        _pii_masker = PIIMasker()
    return _pii_masker
