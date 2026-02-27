"""数据库会话管理。"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from tkp_api.core.config import get_settings

settings = get_settings()

# 全局数据库引擎，开启连接预检查以减少僵尸连接影响。
engine = create_engine(settings.database_url, future=True, pool_pre_ping=True)
# 统一会话工厂，路由层通过依赖注入获取短生命周期会话。
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)


def get_db() -> Generator[Session, None, None]:
    """为每个请求提供独立数据库会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
