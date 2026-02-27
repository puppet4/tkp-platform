"""认证相关模型。"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from tkp_api.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class UserCredential(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """用户本地凭据（邮箱密码）关系。"""

    __tablename__ = "user_credentials"
    __table_args__ = (UniqueConstraint("user_id", name="uk_user_credential_user"),)

    # 用户 ID（逻辑关联 users.id，不声明数据库外键）。
    user_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    # 口令哈希，不存明文。
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    # 凭据状态，例如 active/disabled。
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    # 最近一次修改口令时间。
    password_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
