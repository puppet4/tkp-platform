"""数据库基础模型导出。

仅提供 Base 定义，不执行自动建表或结构同步。
数据库结构由 SQL / 迁移脚本维护。
"""

from tkp_api.models.base import Base

__all__ = ["Base"]
