"""统一日志配置。

提供结构化日志配置，支持开发和生产环境。
"""

import logging
import sys
from typing import Any

from tkp_api.core.config import get_settings


class StructuredFormatter(logging.Formatter):
    """结构化日志格式化器（JSON格式）。"""

    def format(self, record: logging.LogRecord) -> str:
        """格式化日志记录为 JSON。"""
        import orjson
        from datetime import datetime

        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # 添加额外字段
        if hasattr(record, "request_id"):
            log_data["request_id"] = record.request_id
        if hasattr(record, "user_id"):
            log_data["user_id"] = record.user_id
        if hasattr(record, "tenant_id"):
            log_data["tenant_id"] = record.tenant_id
        if hasattr(record, "duration_ms"):
            log_data["duration_ms"] = record.duration_ms
        if hasattr(record, "slow_request"):
            log_data["slow_request"] = record.slow_request

        # 添加异常信息
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # 使用 orjson 进行高性能序列化
        return orjson.dumps(log_data).decode('utf-8')


def setup_logging() -> None:
    """配置统一的日志格式。

    开发环境：人类可读的格式
    生产环境：JSON 格式（便于日志收集和分析）
    """
    settings = get_settings()

    # 确定日志级别
    log_level = getattr(logging, settings.app_log_level.upper(), logging.INFO)

    # 创建处理器
    handler = logging.StreamHandler(sys.stdout)

    # 根据环境选择格式
    if settings.app_env in ("prod", "production"):
        # 生产环境：JSON 格式
        formatter = StructuredFormatter()
    else:
        # 开发环境：人类可读格式
        formatter = logging.Formatter(
            fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    handler.setFormatter(formatter)

    # 配置根日志记录器
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()  # 清除现有处理器
    root_logger.addHandler(handler)

    # 配置第三方库日志级别（避免过多噪音）
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    # 记录日志配置完成
    logger = logging.getLogger(__name__)
    logger.info(
        f"Logging configured: level={settings.app_log_level}, env={settings.app_env}, format={'JSON' if settings.app_env in ('prod', 'production') else 'TEXT'}"
    )


def get_logger(name: str) -> logging.Logger:
    """获取日志记录器。

    Args:
        name: 日志记录器名称（通常使用 __name__）

    Returns:
        配置好的日志记录器
    """
    return logging.getLogger(name)
