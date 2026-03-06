"""健康检查和就绪探针。

提供 Kubernetes 风格的健康检查端点。
"""

import logging
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger("tkp_api.observability.health")


class HealthChecker:
    """健康检查器。"""

    def __init__(self):
        """初始化健康检查器。"""
        self.checks = {}

    def register_check(self, name: str, check_func):
        """注册健康检查函数。

        Args:
            name: 检查名称
            check_func: 检查函数，返回 (bool, str) 表示 (是否健康, 详情)
        """
        self.checks[name] = check_func
        logger.info("registered health check: %s", name)

    def check_all(self) -> dict[str, Any]:
        """执行所有健康检查。

        Returns:
            包含 status、checks 的字典
        """
        results = {}
        all_healthy = True

        for name, check_func in self.checks.items():
            try:
                healthy, detail = check_func()
                results[name] = {
                    "status": "healthy" if healthy else "unhealthy",
                    "detail": detail,
                }
                if not healthy:
                    all_healthy = False
            except Exception as exc:
                logger.exception("health check failed: %s", name)
                results[name] = {
                    "status": "unhealthy",
                    "detail": str(exc),
                }
                all_healthy = False

        return {
            "status": "healthy" if all_healthy else "unhealthy",
            "checks": results,
        }

    def check_liveness(self) -> dict[str, Any]:
        """存活检查（简单检查，服务是否运行）。"""
        return {
            "status": "healthy",
            "message": "service is alive",
        }

    def check_readiness(self) -> dict[str, Any]:
        """就绪检查（完整检查，服务是否可以接受流量）。"""
        return self.check_all()


def check_database(db: Session) -> tuple[bool, str]:
    """检查数据库连接。"""
    try:
        from sqlalchemy import text

        result = db.execute(text("SELECT 1"))
        result.fetchone()
        return True, "database connection ok"
    except Exception as exc:
        logger.exception("database health check failed")
        return False, f"database connection failed: {exc}"


def check_redis(redis_client) -> tuple[bool, str]:
    """检查 Redis 连接。"""
    try:
        if redis_client is None:
            return True, "redis not configured"
        redis_client.ping()
        return True, "redis connection ok"
    except Exception as exc:
        logger.exception("redis health check failed")
        return False, f"redis connection failed: {exc}"


def check_elasticsearch(es_client) -> tuple[bool, str]:
    """检查 Elasticsearch 连接。"""
    try:
        if es_client is None:
            return True, "elasticsearch not configured"
        health = es_client.client.cluster.health()
        status = health["status"]
        return status in ["green", "yellow"], f"elasticsearch status: {status}"
    except Exception as exc:
        logger.exception("elasticsearch health check failed")
        return False, f"elasticsearch connection failed: {exc}"


def check_openai_api(api_key: str) -> tuple[bool, str]:
    """检查 OpenAI API 连接。"""
    try:
        if not api_key:
            return False, "openai api key not configured"

        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        # 简单调用测试连接
        models = client.models.list()
        return True, f"openai api ok, {len(list(models.data))} models available"
    except Exception as exc:
        logger.exception("openai api health check failed")
        return False, f"openai api failed: {exc}"


# 全局健康检查器实例
_health_checker = None


def get_health_checker() -> HealthChecker:
    """获取全局健康检查器实例。"""
    global _health_checker
    if _health_checker is None:
        _health_checker = HealthChecker()
    return _health_checker


def init_health_checks(
    *,
    db: Session,
    redis_client=None,
    es_client=None,
    openai_api_key: str | None = None,
):
    """初始化健康检查。"""
    checker = get_health_checker()

    # 注册数据库检查
    checker.register_check("database", lambda: check_database(db))

    # 注册 Redis 检查
    if redis_client:
        checker.register_check("redis", lambda: check_redis(redis_client))

    # 注册 Elasticsearch 检查
    if es_client:
        checker.register_check("elasticsearch", lambda: check_elasticsearch(es_client))

    # 注册 OpenAI API 检查
    if openai_api_key:
        checker.register_check("openai", lambda: check_openai_api(openai_api_key))

    logger.info("health checks initialized")
