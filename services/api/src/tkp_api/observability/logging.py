"""结构化日志配置。

支持 JSON 格式日志输出，便于日志聚合系统（ELK/Loki）处理。
"""

import logging
import sys
from typing import Any


class JSONFormatter(logging.Formatter):
    """JSON 格式日志格式化器。"""

    def format(self, record: logging.LogRecord) -> str:
        """格式化日志记录为 JSON。"""
        import json
        from datetime import datetime

        log_data = {
            "timestamp": datetime.utcfromtimestamp(record.created).isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # 添加异常信息
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # 添加额外字段
        if hasattr(record, "tenant_id"):
            log_data["tenant_id"] = record.tenant_id
        if hasattr(record, "user_id"):
            log_data["user_id"] = record.user_id
        if hasattr(record, "request_id"):
            log_data["request_id"] = record.request_id
        if hasattr(record, "trace_id"):
            log_data["trace_id"] = record.trace_id
        if hasattr(record, "span_id"):
            log_data["span_id"] = record.span_id

        return json.dumps(log_data, ensure_ascii=False)


def setup_logging(
    *,
    level: str = "INFO",
    format_type: str = "json",
    service_name: str = "tkp_api",
) -> None:
    """配置日志系统。

    Args:
        level: 日志级别
        format_type: 格式类型（json/text）
        service_name: 服务名称
    """
    # 设置根日志级别
    logging.root.setLevel(level)

    # 移除现有处理器
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)

    # 创建控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)

    # 设置格式化器
    if format_type == "json":
        formatter = JSONFormatter()
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    console_handler.setFormatter(formatter)
    logging.root.addHandler(console_handler)

    # 设置第三方库日志级别
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("fastapi").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    logging.info("logging configured: level=%s, format=%s, service=%s", level, format_type, service_name)


class LogContext:
    """日志上下文管理器。

    用于在日志中添加上下文信息（如 tenant_id、user_id、request_id）。
    """

    def __init__(self, **kwargs):
        """初始化日志上下文。"""
        self.context = kwargs
        self.old_factory = None

    def __enter__(self):
        """进入上下文。"""
        self.old_factory = logging.getLogRecordFactory()

        def record_factory(*args, **kwargs):
            record = self.old_factory(*args, **kwargs)
            for key, value in self.context.items():
                setattr(record, key, value)
            return record

        logging.setLogRecordFactory(record_factory)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出上下文。"""
        if self.old_factory:
            logging.setLogRecordFactory(self.old_factory)


def add_trace_context_to_logs():
    """将 OpenTelemetry trace context 添加到日志。"""
    try:
        from opentelemetry import trace

        old_factory = logging.getLogRecordFactory()

        def record_factory(*args, **kwargs):
            record = old_factory(*args, **kwargs)
            span = trace.get_current_span()
            if span:
                ctx = span.get_span_context()
                if ctx.is_valid:
                    record.trace_id = format(ctx.trace_id, "032x")
                    record.span_id = format(ctx.span_id, "016x")
            return record

        logging.setLogRecordFactory(record_factory)
        logging.info("trace context added to logs")
    except ImportError:
        logging.warning("OpenTelemetry not available, trace context not added to logs")
