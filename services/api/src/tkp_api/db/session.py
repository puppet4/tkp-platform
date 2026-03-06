"""数据库会话管理。"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from tkp_api.core.config import get_settings

settings = get_settings()

# 全局数据库引擎，配置连接池以支持高并发
engine = create_engine(
    settings.database_url,
    future=True,
    pool_pre_ping=True,  # 连接前检查，避免使用僵尸连接
    pool_size=20,  # 连接池大小
    max_overflow=10,  # 最大溢出连接数
    pool_timeout=30,  # 获取连接超时时间（秒）
    pool_recycle=3600,  # 连接回收时间（秒），避免长时间连接被数据库关闭
    echo=settings.app_debug,  # 开发模式下打印 SQL
)
# 统一会话工厂，路由层通过依赖注入获取短生命周期会话。
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)


def get_db() -> Generator[Session, None, None]:
    """为每个请求提供独立数据库会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
