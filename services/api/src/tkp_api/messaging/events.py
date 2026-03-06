"""事件定义模块。

定义系统中的各种事件类型。
"""

from datetime import datetime
from typing import Any
from uuid import UUID


class Event:
    """基础事件类。"""

    def __init__(
        self,
        *,
        event_type: str,
        entity_id: UUID,
        tenant_id: UUID,
        data: dict[str, Any],
        timestamp: datetime | None = None,
    ):
        """初始化事件。"""
        self.event_type = event_type
        self.entity_id = entity_id
        self.tenant_id = tenant_id
        self.data = data
        self.timestamp = timestamp or datetime.utcnow()

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            "event_type": self.event_type,
            "entity_id": str(self.entity_id),
            "tenant_id": str(self.tenant_id),
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
        }


# 文档事件

class DocumentUploadedEvent(Event):
    """文档上传事件。"""

    def __init__(
        self,
        *,
        document_id: UUID,
        tenant_id: UUID,
        kb_id: UUID,
        filename: str,
        file_size: int,
        uploaded_by: UUID,
    ):
        super().__init__(
            event_type="document.uploaded",
            entity_id=document_id,
            tenant_id=tenant_id,
            data={
                "kb_id": str(kb_id),
                "filename": filename,
                "file_size": file_size,
                "uploaded_by": str(uploaded_by),
            },
        )


class DocumentProcessedEvent(Event):
    """文档处理完成事件。"""

    def __init__(
        self,
        *,
        document_id: UUID,
        tenant_id: UUID,
        kb_id: UUID,
        chunk_count: int,
        processing_time: float,
        success: bool,
    ):
        super().__init__(
            event_type="document.processed",
            entity_id=document_id,
            tenant_id=tenant_id,
            data={
                "kb_id": str(kb_id),
                "chunk_count": chunk_count,
                "processing_time": processing_time,
                "success": success,
            },
        )


class DocumentDeletedEvent(Event):
    """文档删除事件。"""

    def __init__(
        self,
        *,
        document_id: UUID,
        tenant_id: UUID,
        kb_id: UUID,
        deleted_by: UUID,
    ):
        super().__init__(
            event_type="document.deleted",
            entity_id=document_id,
            tenant_id=tenant_id,
            data={
                "kb_id": str(kb_id),
                "deleted_by": str(deleted_by),
            },
        )


# 检索事件

class RetrievalQueryEvent(Event):
    """检索查询事件。"""

    def __init__(
        self,
        *,
        query_id: UUID,
        tenant_id: UUID,
        kb_ids: list[UUID],
        query: str,
        strategy: str,
        hit_count: int,
        latency_ms: int,
    ):
        super().__init__(
            event_type="retrieval.query",
            entity_id=query_id,
            tenant_id=tenant_id,
            data={
                "kb_ids": [str(kb_id) for kb_id in kb_ids],
                "query": query,
                "strategy": strategy,
                "hit_count": hit_count,
                "latency_ms": latency_ms,
            },
        )


# 聊天事件

class ChatMessageEvent(Event):
    """聊天消息事件。"""

    def __init__(
        self,
        *,
        message_id: UUID,
        tenant_id: UUID,
        conversation_id: UUID,
        role: str,
        content: str,
        token_count: int,
    ):
        super().__init__(
            event_type="chat.message",
            entity_id=message_id,
            tenant_id=tenant_id,
            data={
                "conversation_id": str(conversation_id),
                "role": role,
                "content": content,
                "token_count": token_count,
            },
        )


# Agent 事件

class AgentRunEvent(Event):
    """Agent 运行事件。"""

    def __init__(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        user_id: UUID,
        task: str,
        status: str,
        duration: float | None = None,
    ):
        super().__init__(
            event_type="agent.run",
            entity_id=run_id,
            tenant_id=tenant_id,
            data={
                "user_id": str(user_id),
                "task": task,
                "status": status,
                "duration": duration,
            },
        )


# 用户事件

class UserCreatedEvent(Event):
    """用户创建事件。"""

    def __init__(
        self,
        *,
        user_id: UUID,
        tenant_id: UUID,
        email: str,
    ):
        super().__init__(
            event_type="user.created",
            entity_id=user_id,
            tenant_id=tenant_id,
            data={
                "email": email,
            },
        )


# 租户事件

class TenantCreatedEvent(Event):
    """租户创建事件。"""

    def __init__(
        self,
        *,
        tenant_id: UUID,
        name: str,
    ):
        super().__init__(
            event_type="tenant.created",
            entity_id=tenant_id,
            tenant_id=tenant_id,
            data={
                "name": name,
            },
        )
