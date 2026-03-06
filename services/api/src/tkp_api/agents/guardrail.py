"""Agent Guardrail 模块。

提供内容安全检查、敏感信息过滤、输出验证等功能。
"""

import logging
import re
from typing import Any

logger = logging.getLogger("tkp_api.agents.guardrail")


class ContentGuardrail:
    """内容安全防护。"""

    def __init__(self):
        """初始化内容防护。"""
        # 敏感词列表
        self.sensitive_patterns = [
            re.compile(r"\b(password|passwd|pwd)\s*[:=]\s*\S+", re.IGNORECASE),
            re.compile(r"\b(api[_-]?key|apikey)\s*[:=]\s*\S+", re.IGNORECASE),
            re.compile(r"\b(secret|token)\s*[:=]\s*\S+", re.IGNORECASE),
            re.compile(r"\b(credit[_-]?card|creditcard)\s*[:=]?\s*\d{13,19}", re.IGNORECASE),
        ]

        # 危险操作模式
        self.dangerous_patterns = [
            re.compile(r"\brm\s+-rf\s+/", re.IGNORECASE),
            re.compile(r"\bformat\s+[a-z]:", re.IGNORECASE),
            re.compile(r"\bdrop\s+database", re.IGNORECASE),
            re.compile(r"\bdelete\s+from\s+\w+\s+where\s+1\s*=\s*1", re.IGNORECASE),
        ]

    def check_input(self, text: str) -> dict[str, Any]:
        """检查输入内容安全性。

        Args:
            text: 输入文本

        Returns:
            包含 safe、issues 的字典
        """
        issues = []

        # 检查敏感信息
        for pattern in self.sensitive_patterns:
            if pattern.search(text):
                issues.append({
                    "type": "sensitive_info",
                    "severity": "high",
                    "message": "Input contains sensitive information",
                })

        # 检查危险操作
        for pattern in self.dangerous_patterns:
            if pattern.search(text):
                issues.append({
                    "type": "dangerous_operation",
                    "severity": "critical",
                    "message": "Input contains potentially dangerous operations",
                })

        return {
            "safe": len(issues) == 0,
            "issues": issues,
        }

    def check_output(self, text: str) -> dict[str, Any]:
        """检查输出内容安全性。

        Args:
            text: 输出文本

        Returns:
            包含 safe、issues、sanitized_text 的字典
        """
        issues = []
        sanitized_text = text

        # 检查并移除敏感信息
        for pattern in self.sensitive_patterns:
            matches = pattern.findall(text)
            if matches:
                issues.append({
                    "type": "sensitive_info_in_output",
                    "severity": "high",
                    "message": "Output contains sensitive information",
                })
                # 脱敏
                sanitized_text = pattern.sub("[REDACTED]", sanitized_text)

        return {
            "safe": len(issues) == 0,
            "issues": issues,
            "sanitized_text": sanitized_text,
        }


class ToolGuardrail:
    """工具调用防护。"""

    def __init__(self, allowed_tools: list[str]):
        """初始化工具防护。

        Args:
            allowed_tools: 允许的工具列表
        """
        self.allowed_tools = set(allowed_tools)

    def check_tool_call(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """检查工具调用是否安全。

        Args:
            tool_name: 工具名称
            arguments: 工具参数

        Returns:
            包含 allowed、reason 的字典
        """
        # 检查工具是否在白名单中
        if tool_name not in self.allowed_tools:
            return {
                "allowed": False,
                "reason": f"Tool '{tool_name}' is not in the allowed list",
            }

        # 检查参数
        if not isinstance(arguments, dict):
            return {
                "allowed": False,
                "reason": "Tool arguments must be a dictionary",
            }

        # 工具特定的检查
        if tool_name == "execute_code":
            if "code" not in arguments:
                return {
                    "allowed": False,
                    "reason": "Missing required argument 'code'",
                }

        return {
            "allowed": True,
            "reason": None,
        }


class RateLimitGuardrail:
    """速率限制防护。"""

    def __init__(self, max_calls_per_minute: int = 60):
        """初始化速率限制。

        Args:
            max_calls_per_minute: 每分钟最大调用次数
        """
        self.max_calls_per_minute = max_calls_per_minute
        self.call_history = {}

    def check_rate_limit(self, user_id: str) -> dict[str, Any]:
        """检查速率限制。

        Args:
            user_id: 用户 ID

        Returns:
            包含 allowed、remaining、reset_at 的字典
        """
        import time

        current_time = time.time()
        window_start = current_time - 60

        # 清理过期记录
        if user_id in self.call_history:
            self.call_history[user_id] = [
                t for t in self.call_history[user_id] if t > window_start
            ]
        else:
            self.call_history[user_id] = []

        # 检查是否超限
        call_count = len(self.call_history[user_id])
        if call_count >= self.max_calls_per_minute:
            oldest_call = min(self.call_history[user_id])
            reset_at = oldest_call + 60

            return {
                "allowed": False,
                "remaining": 0,
                "reset_at": reset_at,
            }

        # 记录本次调用
        self.call_history[user_id].append(current_time)

        return {
            "allowed": True,
            "remaining": self.max_calls_per_minute - call_count - 1,
            "reset_at": current_time + 60,
        }


class GuardrailService:
    """Guardrail 服务。"""

    def __init__(
        self,
        *,
        allowed_tools: list[str],
        max_calls_per_minute: int = 60,
    ):
        """初始化 Guardrail 服务。"""
        self.content_guardrail = ContentGuardrail()
        self.tool_guardrail = ToolGuardrail(allowed_tools)
        self.rate_limit_guardrail = RateLimitGuardrail(max_calls_per_minute)

    def validate_agent_input(self, user_id: str, input_text: str) -> dict[str, Any]:
        """验证 Agent 输入。

        Args:
            user_id: 用户 ID
            input_text: 输入文本

        Returns:
            包含 valid、issues 的字典
        """
        issues = []

        # 检查速率限制
        rate_limit_result = self.rate_limit_guardrail.check_rate_limit(user_id)
        if not rate_limit_result["allowed"]:
            issues.append({
                "type": "rate_limit",
                "severity": "high",
                "message": "Rate limit exceeded",
                "reset_at": rate_limit_result["reset_at"],
            })

        # 检查内容安全
        content_result = self.content_guardrail.check_input(input_text)
        if not content_result["safe"]:
            issues.extend(content_result["issues"])

        return {
            "valid": len(issues) == 0,
            "issues": issues,
        }

    def validate_tool_call(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """验证工具调用。

        Args:
            tool_name: 工具名称
            arguments: 工具参数

        Returns:
            包含 valid、reason 的字典
        """
        result = self.tool_guardrail.check_tool_call(tool_name, arguments)
        return {
            "valid": result["allowed"],
            "reason": result["reason"],
        }

    def sanitize_output(self, output_text: str) -> dict[str, Any]:
        """清理输出内容。

        Args:
            output_text: 输出文本

        Returns:
            包含 safe、sanitized_text、issues 的字典
        """
        return self.content_guardrail.check_output(output_text)


# 全局实例
_guardrail_service = None


def get_guardrail_service(allowed_tools: list[str] | None = None) -> GuardrailService:
    """获取全局 Guardrail 服务实例。"""
    global _guardrail_service
    if _guardrail_service is None:
        from tkp_api.core.config import get_settings

        settings = get_settings()
        _guardrail_service = GuardrailService(
            allowed_tools=allowed_tools or settings.agent_allowed_tools_list,
            max_calls_per_minute=60,
        )
    return _guardrail_service
