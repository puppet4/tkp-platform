"""消息队列模块。

提供 Kafka 事件总线和事件定义。
"""

from tkp_api.messaging.events import (
    Event,
    DocumentUploadedEvent,
    DocumentProcessedEvent,
    DocumentDeletedEvent,
    RetrievalQueryEvent,
    ChatMessageEvent,
    AgentRunEvent,
    UserCreatedEvent,
    TenantCreatedEvent,
)
from tkp_api.messaging.kafka import (
    KafkaProducer,
    KafkaConsumer,
    EventBus,
    create_kafka_producer,
    create_kafka_consumer,
)

__all__ = [
    "KafkaProducer",
    "KafkaConsumer",
    "EventBus",
    "create_kafka_producer",
    "create_kafka_consumer",
    "Event",
    "DocumentUploadedEvent",
    "DocumentProcessedEvent",
    "DocumentDeletedEvent",
    "RetrievalQueryEvent",
    "ChatMessageEvent",
    "AgentRunEvent",
    "UserCreatedEvent",
    "TenantCreatedEvent",
]
