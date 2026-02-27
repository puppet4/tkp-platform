"""对象映射基础模型与通用混入。"""

from datetime import datetime
from uuid import UUID
from uuid import uuid4

from sqlalchemy import DateTime, MetaData, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """全局对象映射声明基类。"""

    metadata = MetaData(
        naming_convention={
            # 统一约束/索引命名规范（无外键场景）。
            "pk": "pk_%(table_name)s",
            "ix": "ix_%(table_name)s_%(column_0_name)s",
            "uq": "uk_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
        }
    )


class UUIDPrimaryKeyMixin:
    """提供统一 UUID 主键字段。"""

    # 所有业务表统一使用 UUID 主键，便于跨系统合并与脱敏。
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4, comment="主键 ID。")


class TimestampMixin:
    """提供创建时间与更新时间字段。"""

    # 记录创建时间。
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, comment="创建时间。"
    )
    # 记录最后更新时间，更新时自动刷新。
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="更新时间。",
    )
