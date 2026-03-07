"""可观测性模块。

提供分布式追踪、指标收集、结构化日志、健康检查等功能。
"""

from tkp_api.observability.health import (
    HealthChecker,
    get_health_checker,
    init_health_checks,
)
from tkp_api.observability.logging import (
    setup_logging,
    LogContext,
    add_trace_context_to_logs,
)
from tkp_api.observability.metrics import MetricsCollector, get_metrics_collector
from tkp_api.observability.telemetry import (
    init_telemetry,
    instrument_fastapi,
    instrument_sqlalchemy,
    instrument_redis,
    get_tracer,
    get_meter,
)

__all__ = [
    "init_telemetry",
    "instrument_fastapi",
    "instrument_sqlalchemy",
    "instrument_redis",
    "get_tracer",
    "get_meter",
    "MetricsCollector",
    "get_metrics_collector",
    "setup_logging",
    "LogContext",
    "add_trace_context_to_logs",
    "HealthChecker",
    "get_health_checker",
    "init_health_checks",
]
