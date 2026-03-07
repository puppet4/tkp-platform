"""数据库会话管理。"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from tkp_api.core.config import get_settings
from tkp_api.core.context import get_request_context

settings = get_settings()

# 全局数据库引擎，配置连接池以支持高并发
engine = create_engine(
    settings.database_url,
    future=True,
    pool_pre_ping=True,  # 连接前检查，避免使用僵尸连接
    pool_size=settings.database_pool_size,  # 连接池大小（可配置）
    max_overflow=settings.database_max_overflow,  # 最大溢出连接数（可配置）
    pool_timeout=settings.database_pool_timeout,  # 获取连接超时时间（秒）
    pool_recycle=settings.database_pool_recycle,  # 连接回收时间（秒），避免长时间连接被数据库关闭
    echo=settings.app_debug,  # 开发模式下打印 SQL
)
# 统一会话工厂，路由层通过依赖注入获取短生命周期会话。
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)


def get_db() -> Generator[Session, None, None]:
    """为每个请求提供独立数据库会话。

    优先从 contextvars 获取 TransactionMiddleware 创建的会话。
    如果不存在（如测试环境），则创建新会话。

    注意：事务管理由 TransactionMiddleware 统一处理，
    此函数只负责提供会话引用。
    """
    # 尝试从 contextvars 获取请求上下文
    request = get_request_context()

    if request is not None and hasattr(request, "state") and hasattr(request.state, "db"):
        # 使用中间件创建的会话（正常请求流程）
        yield request.state.db
    else:
        # 回退方案：创建临时会话（用于测试或非 HTTP 上下文）
        db = SessionLocal()
        try:
            yield db
            # 在回退模式下，需要手动提交
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


def get_engine_stats() -> dict:
    """获取数据库连接池统计信息。

    Returns:
        连接池状态字典
    """
    pool = engine.pool
    return {
        "pool_size": pool.size(),
        "checked_in": pool.checkedin(),
        "checked_out": pool.checkedout(),
        "overflow": pool.overflow(),
        "total_connections": pool.size() + pool.overflow(),
    }
