"""OpenTelemetry 分布式追踪和指标集成。

提供统一的可观测性基础设施。
"""

import logging
from typing import Any

logger = logging.getLogger("tkp_api.observability.telemetry")


def init_telemetry(
    *,
    service_name: str,
    service_version: str = "1.0.0",
    otlp_endpoint: str | None = None,
    enable_traces: bool = True,
    enable_metrics: bool = True,
    enable_logs: bool = False,
) -> dict[str, Any]:
    """初始化 OpenTelemetry。

    Args:
        service_name: 服务名称
        service_version: 服务版本
        otlp_endpoint: OTLP 导出端点（如 Jaeger、Tempo）
        enable_traces: 是否启用追踪
        enable_metrics: 是否启用指标
        enable_logs: 是否启用日志

    Returns:
        包含 tracer_provider、meter_provider 的字典
    """
    try:
        from opentelemetry import trace, metrics
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        from opentelemetry.instrumentation.redis import RedisInstrumentor
    except ImportError as exc:
        logger.warning("OpenTelemetry packages not installed: %s", exc)
        return {}

    # 创建资源标识
    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": service_version,
        }
    )

    result = {}

    # 初始化追踪
    if enable_traces:
        tracer_provider = TracerProvider(resource=resource)

        if otlp_endpoint:
            # 配置 OTLP 导出器
            otlp_exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
            span_processor = BatchSpanProcessor(otlp_exporter)
            tracer_provider.add_span_processor(span_processor)
        else:
            # 使用控制台导出器（开发环境）
            from opentelemetry.sdk.trace.export import ConsoleSpanExporter

            console_exporter = ConsoleSpanExporter()
            span_processor = BatchSpanProcessor(console_exporter)
            tracer_provider.add_span_processor(span_processor)

        trace.set_tracer_provider(tracer_provider)
        result["tracer_provider"] = tracer_provider
        logger.info("OpenTelemetry traces initialized: endpoint=%s", otlp_endpoint or "console")

    # 初始化指标
    if enable_metrics:
        if otlp_endpoint:
            metric_exporter = OTLPMetricExporter(endpoint=otlp_endpoint, insecure=True)
        else:
            from opentelemetry.sdk.metrics.export import ConsoleMetricExporter

            metric_exporter = ConsoleMetricExporter()

        metric_reader = PeriodicExportingMetricReader(metric_exporter, export_interval_millis=60000)
        meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
        metrics.set_meter_provider(meter_provider)
        result["meter_provider"] = meter_provider
        logger.info("OpenTelemetry metrics initialized: endpoint=%s", otlp_endpoint or "console")

    return result


def instrument_fastapi(app):
    """为 FastAPI 应用添加自动追踪。"""
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
        logger.info("FastAPI instrumentation enabled")
    except Exception as exc:
        logger.warning("Failed to instrument FastAPI: %s", exc)


def instrument_sqlalchemy(engine):
    """为 SQLAlchemy 引擎添加自动追踪。"""
    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        SQLAlchemyInstrumentor().instrument(engine=engine)
        logger.info("SQLAlchemy instrumentation enabled")
    except Exception as exc:
        logger.warning("Failed to instrument SQLAlchemy: %s", exc)


def instrument_redis(client):
    """为 Redis 客户端添加自动追踪。"""
    try:
        from opentelemetry.instrumentation.redis import RedisInstrumentor

        RedisInstrumentor().instrument()
        logger.info("Redis instrumentation enabled")
    except Exception as exc:
        logger.warning("Failed to instrument Redis: %s", exc)


def get_tracer(name: str):
    """获取追踪器。"""
    try:
        from opentelemetry import trace

        return trace.get_tracer(name)
    except ImportError:
        return None


def get_meter(name: str):
    """获取指标器。"""
    try:
        from opentelemetry import metrics

        return metrics.get_meter(name)
    except ImportError:
        return None
