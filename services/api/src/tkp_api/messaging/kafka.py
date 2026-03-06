"""Kafka 消息队列封装。

提供事件发布和订阅功能。
"""

import json
import logging
from typing import Any, Callable

logger = logging.getLogger("tkp_api.messaging.kafka")


class KafkaProducer:
    """Kafka 生产者。"""

    def __init__(
        self,
        *,
        bootstrap_servers: list[str],
        client_id: str = "tkp-api",
    ):
        """初始化 Kafka 生产者。

        Args:
            bootstrap_servers: Kafka 服务器地址列表
            client_id: 客户端 ID
        """
        try:
            from kafka import KafkaProducer as _KafkaProducer
        except ImportError as exc:
            raise RuntimeError("Kafka producer requires 'kafka-python' package") from exc

        self.producer = _KafkaProducer(
            bootstrap_servers=bootstrap_servers,
            client_id=client_id,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8") if k else None,
        )

        logger.info("kafka producer initialized: servers=%s", bootstrap_servers)

    def send(
        self,
        topic: str,
        value: dict[str, Any],
        key: str | None = None,
    ) -> bool:
        """发送消息。

        Args:
            topic: 主题名称
            value: 消息内容
            key: 消息键（可选）

        Returns:
            是否发送成功
        """
        try:
            future = self.producer.send(topic, value=value, key=key)
            # 等待发送完成
            record_metadata = future.get(timeout=10)

            logger.debug(
                "message sent: topic=%s, partition=%d, offset=%d",
                record_metadata.topic,
                record_metadata.partition,
                record_metadata.offset,
            )
            return True
        except Exception as exc:
            logger.exception("failed to send message: %s", exc)
            return False

    def close(self):
        """关闭生产者。"""
        try:
            self.producer.close()
            logger.info("kafka producer closed")
        except Exception as exc:
            logger.exception("failed to close producer: %s", exc)


class KafkaConsumer:
    """Kafka 消费者。"""

    def __init__(
        self,
        *,
        topics: list[str],
        bootstrap_servers: list[str],
        group_id: str,
        auto_offset_reset: str = "earliest",
    ):
        """初始化 Kafka 消费者。

        Args:
            topics: 订阅的主题列表
            bootstrap_servers: Kafka 服务器地址列表
            group_id: 消费者组 ID
            auto_offset_reset: 偏移量重置策略
        """
        try:
            from kafka import KafkaConsumer as _KafkaConsumer
        except ImportError as exc:
            raise RuntimeError("Kafka consumer requires 'kafka-python' package") from exc

        self.consumer = _KafkaConsumer(
            *topics,
            bootstrap_servers=bootstrap_servers,
            group_id=group_id,
            auto_offset_reset=auto_offset_reset,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            key_deserializer=lambda k: k.decode("utf-8") if k else None,
        )

        logger.info(
            "kafka consumer initialized: topics=%s, group_id=%s",
            topics,
            group_id,
        )

    def consume(self, handler: Callable[[dict[str, Any]], None]):
        """消费消息。

        Args:
            handler: 消息处理函数
        """
        try:
            for message in self.consumer:
                try:
                    logger.debug(
                        "message received: topic=%s, partition=%d, offset=%d",
                        message.topic,
                        message.partition,
                        message.offset,
                    )

                    handler(message.value)

                    # 提交偏移量
                    self.consumer.commit()
                except Exception as exc:
                    logger.exception("failed to handle message: %s", exc)
        except KeyboardInterrupt:
            logger.info("consumer interrupted")
        finally:
            self.close()

    def close(self):
        """关闭消费者。"""
        try:
            self.consumer.close()
            logger.info("kafka consumer closed")
        except Exception as exc:
            logger.exception("failed to close consumer: %s", exc)


class EventBus:
    """事件总线。"""

    def __init__(self, producer: KafkaProducer):
        """初始化事件总线。

        Args:
            producer: Kafka 生产者
        """
        self.producer = producer

    def publish(
        self,
        event_type: str,
        event_data: dict[str, Any],
        entity_id: str | None = None,
    ) -> bool:
        """发布事件。

        Args:
            event_type: 事件类型
            event_data: 事件数据
            entity_id: 实体 ID（用作消息键）

        Returns:
            是否发布成功
        """
        from datetime import datetime

        event = {
            "event_type": event_type,
            "event_data": event_data,
            "timestamp": datetime.utcnow().isoformat(),
        }

        # 根据事件类型选择主题
        topic = self._get_topic_for_event(event_type)

        return self.producer.send(topic, value=event, key=entity_id)

    def _get_topic_for_event(self, event_type: str) -> str:
        """根据事件类型获取主题名称。"""
        # 事件类型到主题的映射
        event_topic_map = {
            "document.uploaded": "document-events",
            "document.processed": "document-events",
            "document.deleted": "document-events",
            "retrieval.query": "retrieval-events",
            "chat.message": "chat-events",
            "agent.run": "agent-events",
            "user.created": "user-events",
            "tenant.created": "tenant-events",
        }

        return event_topic_map.get(event_type, "default-events")


def create_kafka_producer(
    *,
    bootstrap_servers: str,
    client_id: str = "tkp-api",
) -> KafkaProducer:
    """创建 Kafka 生产者的工厂函数。"""
    servers = [s.strip() for s in bootstrap_servers.split(",")]
    return KafkaProducer(
        bootstrap_servers=servers,
        client_id=client_id,
    )


def create_kafka_consumer(
    *,
    topics: str,
    bootstrap_servers: str,
    group_id: str,
    auto_offset_reset: str = "earliest",
) -> KafkaConsumer:
    """创建 Kafka 消费者的工厂函数。"""
    topic_list = [t.strip() for t in topics.split(",")]
    servers = [s.strip() for s in bootstrap_servers.split(",")]

    return KafkaConsumer(
        topics=topic_list,
        bootstrap_servers=servers,
        group_id=group_id,
        auto_offset_reset=auto_offset_reset,
    )


def create_event_bus(producer: KafkaProducer) -> EventBus:
    """创建事件总线的工厂函数。"""
    return EventBus(producer)
