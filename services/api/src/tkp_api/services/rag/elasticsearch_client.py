"""Elasticsearch 全文检索客户端。

用于实现混合检索（向量 + 全文）。
"""

import logging
from typing import Any
from uuid import UUID

logger = logging.getLogger("tkp_api.rag.elasticsearch")


class ElasticsearchClient:
    """Elasticsearch 客户端封装。"""

    def __init__(
        self,
        *,
        hosts: list[str],
        api_key: str | None = None,
        username: str | None = None,
        password: str | None = None,
        verify_certs: bool = True,
    ):
        """初始化 Elasticsearch 客户端。

        Args:
            hosts: Elasticsearch 节点地址列表
            api_key: API Key 认证（可选）
            username: 用户名认证（可选）
            password: 密码认证（可选）
            verify_certs: 是否验证 SSL 证书
        """
        try:
            from elasticsearch import Elasticsearch
        except ImportError as exc:
            raise RuntimeError("Elasticsearch client requires 'elasticsearch' package") from exc

        auth_params = {}
        if api_key:
            auth_params["api_key"] = api_key
        elif username and password:
            auth_params["basic_auth"] = (username, password)

        self.client = Elasticsearch(
            hosts=hosts,
            verify_certs=verify_certs,
            **auth_params,
        )
        logger.info("initialized elasticsearch client: hosts=%s", hosts)

    def create_index(self, index_name: str, mappings: dict[str, Any]) -> bool:
        """创建索引。

        Args:
            index_name: 索引名称
            mappings: 字段映射配置

        Returns:
            是否创建成功
        """
        try:
            if self.client.indices.exists(index=index_name):
                logger.info("index already exists: %s", index_name)
                return True

            self.client.indices.create(
                index=index_name,
                mappings=mappings,
            )
            logger.info("created index: %s", index_name)
            return True
        except Exception as exc:
            logger.exception("failed to create index %s: %s", index_name, exc)
            return False

    def index_document(
        self,
        *,
        index_name: str,
        doc_id: str,
        document: dict[str, Any],
    ) -> bool:
        """索引单个文档。

        Args:
            index_name: 索引名称
            doc_id: 文档 ID
            document: 文档内容

        Returns:
            是否索引成功
        """
        try:
            self.client.index(
                index=index_name,
                id=doc_id,
                document=document,
            )
            return True
        except Exception as exc:
            logger.exception("failed to index document %s: %s", doc_id, exc)
            return False

    def bulk_index(
        self,
        *,
        index_name: str,
        documents: list[dict[str, Any]],
    ) -> tuple[int, int]:
        """批量索引文档。

        Args:
            index_name: 索引名称
            documents: 文档列表，每个文档需包含 _id 字段

        Returns:
            (成功数, 失败数)
        """
        try:
            from elasticsearch.helpers import bulk

            actions = [
                {
                    "_index": index_name,
                    "_id": doc["_id"],
                    "_source": {k: v for k, v in doc.items() if k != "_id"},
                }
                for doc in documents
            ]

            success, failed = bulk(self.client, actions, raise_on_error=False)
            logger.info("bulk indexed: success=%d, failed=%d", success, len(failed))
            return success, len(failed)
        except Exception as exc:
            logger.exception("bulk index failed: %s", exc)
            return 0, len(documents)

    def search(
        self,
        *,
        index_name: str,
        query: dict[str, Any],
        size: int = 10,
        from_: int = 0,
    ) -> list[dict[str, Any]]:
        """执行搜索。

        Args:
            index_name: 索引名称
            query: 查询 DSL
            size: 返回结果数
            from_: 起始位置

        Returns:
            搜索结果列表
        """
        try:
            response = self.client.search(
                index=index_name,
                query=query,
                size=size,
                from_=from_,
            )

            hits = []
            for hit in response["hits"]["hits"]:
                result = {
                    "id": hit["_id"],
                    "score": hit["_score"],
                    **hit["_source"],
                }
                hits.append(result)

            logger.info("search completed: query=%s, hits=%d", query, len(hits))
            return hits
        except Exception as exc:
            logger.exception("search failed: %s", exc)
            return []

    def full_text_search(
        self,
        *,
        index_name: str,
        query_text: str,
        tenant_id: UUID,
        kb_ids: list[UUID] | None = None,
        size: int = 10,
    ) -> list[dict[str, Any]]:
        """全文检索。

        Args:
            index_name: 索引名称
            query_text: 查询文本
            tenant_id: 租户 ID
            kb_ids: 知识库 ID 列表（可选）
            size: 返回结果数

        Returns:
            检索结果列表
        """
        # 构建查询条件
        must_conditions = [
            {"match": {"content": {"query": query_text, "boost": 2.0}}},
            {"term": {"tenant_id": str(tenant_id)}},
        ]

        if kb_ids:
            must_conditions.append({"terms": {"kb_id": [str(kb_id) for kb_id in kb_ids]}})

        query = {
            "bool": {
                "must": must_conditions,
            }
        }

        return self.search(
            index_name=index_name,
            query=query,
            size=size,
        )

    def delete_document(self, *, index_name: str, doc_id: str) -> bool:
        """删除文档。

        Args:
            index_name: 索引名称
            doc_id: 文档 ID

        Returns:
            是否删除成功
        """
        try:
            self.client.delete(index=index_name, id=doc_id)
            logger.info("deleted document: %s", doc_id)
            return True
        except Exception as exc:
            logger.exception("failed to delete document %s: %s", doc_id, exc)
            return False

    def close(self):
        """关闭客户端连接。"""
        try:
            self.client.close()
            logger.info("elasticsearch client closed")
        except Exception as exc:
            logger.exception("failed to close client: %s", exc)


def create_elasticsearch_client(
    *,
    hosts: list[str],
    api_key: str | None = None,
    username: str | None = None,
    password: str | None = None,
    verify_certs: bool = True,
) -> ElasticsearchClient:
    """创建 Elasticsearch 客户端的工厂函数。"""
    return ElasticsearchClient(
        hosts=hosts,
        api_key=api_key,
        username=username,
        password=password,
        verify_certs=verify_certs,
    )
