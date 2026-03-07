"""业务指标收集器。

收集关键业务指标：请求延迟、错误率、吞吐量等。
"""

import logging
import time
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger("tkp_api.observability.metrics")


class MetricsCollector:
    """指标收集器。"""

    def __init__(self, meter_name: str = "tkp_api"):
        """初始化指标收集器。"""
        self.meter_name = meter_name
        self.meter = None
        self.counters: dict[str, Any] = {}
        self.histograms: dict[str, Any] = {}
        self.gauges: dict[str, Any] = {}

        try:
            from tkp_api.observability.telemetry import get_meter

            self.meter = get_meter(meter_name)
            if self.meter:
                self._init_metrics()
                logger.info("metrics collector initialized")
        except Exception as exc:
            logger.warning("failed to initialize metrics: %s", exc)

    def _init_metrics(self):
        """初始化指标。"""
        if not self.meter:
            return

        # 计数器
        self.counters["requests_total"] = self.meter.create_counter(
            name="requests_total",
            description="Total number of requests",
            unit="1",
        )

        self.counters["requests_errors"] = self.meter.create_counter(
            name="requests_errors",
            description="Total number of failed requests",
            unit="1",
        )

        self.counters["retrieval_requests"] = self.meter.create_counter(
            name="retrieval_requests",
            description="Total number of retrieval requests",
            unit="1",
        )

        self.counters["chat_requests"] = self.meter.create_counter(
            name="chat_requests",
            description="Total number of chat requests",
            unit="1",
        )

        self.counters["document_uploads"] = self.meter.create_counter(
            name="document_uploads",
            description="Total number of document uploads",
            unit="1",
        )

        self.counters["tokens_used"] = self.meter.create_counter(
            name="tokens_used",
            description="Total number of tokens used",
            unit="1",
        )

        # 直方图（延迟）
        self.histograms["request_duration"] = self.meter.create_histogram(
            name="request_duration_seconds",
            description="Request duration in seconds",
            unit="s",
        )

        self.histograms["retrieval_duration"] = self.meter.create_histogram(
            name="retrieval_duration_seconds",
            description="Retrieval duration in seconds",
            unit="s",
        )

        self.histograms["llm_duration"] = self.meter.create_histogram(
            name="llm_duration_seconds",
            description="LLM generation duration in seconds",
            unit="s",
        )

        self.histograms["document_processing_duration"] = self.meter.create_histogram(
            name="document_processing_duration_seconds",
            description="Document processing duration in seconds",
            unit="s",
        )

    def increment_counter(self, name: str, value: int = 1, attributes: dict[str, Any] | None = None):
        """增加计数器。"""
        if not self.meter or name not in self.counters:
            return

        try:
            self.counters[name].add(value, attributes=attributes or {})
        except Exception as exc:
            logger.debug("failed to increment counter %s: %s", name, exc)

    def record_histogram(self, name: str, value: float, attributes: dict[str, Any] | None = None):
        """记录直方图值。"""
        if not self.meter or name not in self.histograms:
            return

        try:
            self.histograms[name].record(value, attributes=attributes or {})
        except Exception as exc:
            logger.debug("failed to record histogram %s: %s", name, exc)

    @contextmanager
    def measure_duration(self, metric_name: str, attributes: dict[str, Any] | None = None):
        """测量代码块执行时间。"""
        start = time.perf_counter()
        try:
            yield
        finally:
            duration = time.perf_counter() - start
            self.record_histogram(metric_name, duration, attributes)

    def record_request(self, method: str, path: str, status_code: int, duration: float):
        """记录 HTTP 请求指标。"""
        attributes = {
            "method": method,
            "path": path,
            "status_code": str(status_code),
        }

        self.increment_counter("requests_total", attributes=attributes)

        if status_code >= 400:
            self.increment_counter("requests_errors", attributes=attributes)

        self.record_histogram("request_duration", duration, attributes)

    def record_retrieval(self, tenant_id: str, strategy: str, hits: int, duration: float):
        """记录检索请求指标。"""
        attributes = {
            "tenant_id": tenant_id,
            "strategy": strategy,
        }

        self.increment_counter("retrieval_requests", attributes=attributes)
        self.record_histogram("retrieval_duration", duration, attributes)

    def record_chat(self, tenant_id: str, tokens: int, duration: float):
        """记录聊天请求指标。"""
        attributes = {"tenant_id": tenant_id}

        self.increment_counter("chat_requests", attributes=attributes)
        self.increment_counter("tokens_used", value=tokens, attributes=attributes)
        self.record_histogram("llm_duration", duration, attributes)

    def record_document_upload(self, tenant_id: str, file_type: str, success: bool):
        """记录文档上传指标。"""
        attributes = {
            "tenant_id": tenant_id,
            "file_type": file_type,
            "success": str(success),
        }

        self.increment_counter("document_uploads", attributes=attributes)

    def record_document_processing(self, tenant_id: str, duration: float, success: bool):
        """记录文档处理指标。"""
        attributes = {
            "tenant_id": tenant_id,
            "success": str(success),
        }

        self.record_histogram("document_processing_duration", duration, attributes)


# 全局指标收集器实例
_metrics_collector = None


def get_metrics_collector() -> MetricsCollector:
    """获取全局指标收集器。"""
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = MetricsCollector()
    return _metrics_collector
