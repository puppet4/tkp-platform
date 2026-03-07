"""Parent-Child Chunk 合并服务。

提供父子块合并返回功能：
- 检索子块（小粒度，精确匹配）
- 返回父块（大粒度，完整上下文）
- 合并相邻块
"""

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from tkp_api.models.knowledge import DocumentChunk

logger = logging.getLogger("tkp_api.parent_child_merger")


class ParentChildMerger:
    """父子块合并器。"""

    def __init__(self, *, enable_merge: bool = True, max_merge_distance: int = 2):
        """初始化父子块合并器。

        Args:
            enable_merge: 是否启用合并
            max_merge_distance: 最大合并距离（相邻块的序号差）
        """
        self.enable_merge = enable_merge
        self.max_merge_distance = max_merge_distance

    def merge_with_parents(
        self,
        db: Session,
        chunks: list[dict[str, Any]],
        tenant_id: UUID,
    ) -> list[dict[str, Any]]:
        """将子块替换为父块。

        Args:
            db: 数据库会话
            chunks: 检索到的子块列表
            tenant_id: 租户 ID

        Returns:
            合并后的块列表（包含父块内容）
        """
        if not self.enable_merge or not chunks:
            return chunks

        merged_chunks = []
        parent_cache = {}  # 缓存已加载的父块

        for chunk in chunks:
            chunk_id = chunk.get("chunk_id")
            parent_chunk_id = chunk.get("parent_chunk_id")

            # 如果没有父块，保持原样
            if not parent_chunk_id:
                merged_chunks.append(chunk)
                continue

            # 从缓存或数据库获取父块
            if parent_chunk_id not in parent_cache:
                parent_chunk = self._load_parent_chunk(db, parent_chunk_id, tenant_id)
                if parent_chunk:
                    parent_cache[parent_chunk_id] = parent_chunk
                else:
                    # 父块不存在，保持原样
                    merged_chunks.append(chunk)
                    continue
            else:
                parent_chunk = parent_cache[parent_chunk_id]

            # 用父块内容替换子块内容
            merged_chunk = chunk.copy()
            merged_chunk["content"] = parent_chunk["content"]
            merged_chunk["original_chunk_id"] = chunk_id  # 保留原始子块 ID
            merged_chunk["chunk_id"] = parent_chunk["chunk_id"]  # 使用父块 ID
            merged_chunk["is_parent"] = True

            merged_chunks.append(merged_chunk)
            logger.debug(
                "merged child chunk %s with parent %s",
                str(chunk_id)[:8],
                str(parent_chunk_id)[:8],
            )

        logger.info("parent-child merge: input=%d, output=%d, parents_used=%d", len(chunks), len(merged_chunks), len(parent_cache))

        return merged_chunks

    def merge_adjacent_chunks(
        self,
        db: Session,
        chunks: list[dict[str, Any]],
        tenant_id: UUID,
    ) -> list[dict[str, Any]]:
        """合并相邻的块。

        如果多个块来自同一文档且序号相邻，则合并为一个块。

        Args:
            db: 数据库会话
            chunks: 块列表
            tenant_id: 租户 ID

        Returns:
            合并后的块列表
        """
        if not self.enable_merge or not chunks:
            return chunks

        # 按文档分组
        doc_groups: dict[UUID, list[dict[str, Any]]] = {}
        for chunk in chunks:
            doc_id = chunk.get("document_id")
            if doc_id:
                if doc_id not in doc_groups:
                    doc_groups[doc_id] = []
                doc_groups[doc_id].append(chunk)

        merged_chunks = []

        for doc_id, doc_chunks in doc_groups.items():
            # 按序号排序
            sorted_chunks = sorted(doc_chunks, key=lambda x: x.get("sequence", 0))

            # 合并相邻块
            i = 0
            while i < len(sorted_chunks):
                current = sorted_chunks[i]
                merge_group = [current]

                # 查找相邻块
                j = i + 1
                while j < len(sorted_chunks):
                    next_chunk = sorted_chunks[j]
                    current_seq = current.get("sequence", 0)
                    next_seq = next_chunk.get("sequence", 0)

                    # 检查是否相邻
                    if next_seq - current_seq <= self.max_merge_distance:
                        merge_group.append(next_chunk)
                        current = next_chunk
                        j += 1
                    else:
                        break

                # 如果有多个块，则合并
                if len(merge_group) > 1:
                    merged_chunk = self._merge_chunk_group(merge_group)
                    merged_chunks.append(merged_chunk)
                    logger.debug("merged %d adjacent chunks from doc %s", len(merge_group), str(doc_id)[:8])
                else:
                    merged_chunks.append(current)

                i = j if j > i + 1 else i + 1

        logger.info("adjacent merge: input=%d, output=%d", len(chunks), len(merged_chunks))

        return merged_chunks

    def _load_parent_chunk(
        self,
        db: Session,
        parent_chunk_id: UUID,
        tenant_id: UUID,
    ) -> dict[str, Any] | None:
        """从数据库加载父块。"""
        try:
            stmt = (
                select(DocumentChunk)
                .where(
                    DocumentChunk.id == parent_chunk_id,
                    DocumentChunk.tenant_id == tenant_id,
                )
            )
            result = db.execute(stmt)
            parent = result.scalar_one_or_none()

            if not parent:
                return None

            return {
                "chunk_id": parent.id,
                "document_id": parent.document_id,
                "content": parent.content,
                "sequence": parent.chunk_no,
                "metadata": parent.metadata_ or {},
            }
        except Exception as exc:
            logger.warning("failed to load parent chunk %s: %s", parent_chunk_id, exc)
            return None

    def _merge_chunk_group(self, chunks: list[dict[str, Any]]) -> dict[str, Any]:
        """合并一组块。"""
        if not chunks:
            return {}

        # 使用第一个块作为基础
        merged = chunks[0].copy()

        # 合并内容
        contents = [chunk.get("content", "") for chunk in chunks]
        merged["content"] = "\n\n".join(contents)

        # 保留所有块的 ID
        merged["merged_chunk_ids"] = [chunk.get("chunk_id") for chunk in chunks]
        merged["merged_count"] = len(chunks)

        # 使用最高的分数
        scores = [chunk.get("score", 0.0) for chunk in chunks]
        merged["score"] = max(scores)

        # 合并元数据
        merged["is_merged"] = True

        return merged


def create_parent_child_merger() -> ParentChildMerger:
    """创建父子块合并器实例。"""
    from tkp_api.core.config import get_settings

    settings = get_settings()

    # 从配置读取参数（如果有的话）
    enable_merge = getattr(settings, "parent_child_merge_enabled", True)
    max_merge_distance = getattr(settings, "parent_child_max_merge_distance", 2)

    return ParentChildMerger(
        enable_merge=enable_merge,
        max_merge_distance=max_merge_distance,
    )
