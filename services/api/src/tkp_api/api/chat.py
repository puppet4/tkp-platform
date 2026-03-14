"""问答接口。"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from tkp_api.db.session import get_db
from tkp_api.dependencies import get_request_context
from tkp_api.models.conversation import Conversation, Message
from tkp_api.models.enums import MessageRole
from tkp_api.schemas.chat import ChatCompletionRequest
from tkp_api.schemas.common import ErrorResponse, SuccessResponse
from tkp_api.schemas.responses import ChatCompletionData
from tkp_api.services import (
    PermissionAction,
    filter_readable_kb_ids,
    generate_chat_answer,
    require_tenant_action,
)
from tkp_api.services.quota import QuotaMetric, enforce_quota, resolve_workspace_scope_for_kbs
from tkp_api.utils.response import success

router = APIRouter(prefix="/chat", tags=["chat"])


# ============ 请求/响应模型 ============

class ConversationCreateRequest(BaseModel):
    """创建会话请求。"""

    kb_ids: list[str] = Field(description="知识库 ID 列表", default_factory=list)
    title: str = Field(description="会话标题", default="新会话", min_length=1, max_length=256)


class ConversationUpdateRequest(BaseModel):
    """更新会话请求。"""

    title: str = Field(description="会话标题", min_length=1, max_length=256)


# ============ 会话管理 API ============

@router.get(
    "/conversations",
    summary="获取会话列表",
    description="获取当前用户的所有会话列表，按最后更新时间倒序排列。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse,
)
def list_conversations(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100, description="每页数量"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """获取会话列表。"""
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.CHAT_COMPLETION,
    )

    # 查询会话列表
    stmt = (
        select(Conversation)
        .where(
            Conversation.tenant_id == ctx.tenant_id,
            Conversation.user_id == ctx.user_id,
        )
        .order_by(desc(Conversation.updated_at))
        .limit(limit)
        .offset(offset)
    )
    result = db.execute(stmt)
    conversations = result.scalars().all()

    # 统计总数
    count_stmt = (
        select(func.count(Conversation.id))
        .where(
            Conversation.tenant_id == ctx.tenant_id,
            Conversation.user_id == ctx.user_id,
        )
    )
    total = db.execute(count_stmt).scalar_one()

    return success(
        request,
        {
            "conversations": [
                {
                    "conversation_id": str(conv.id),
                    "title": conv.title,
                    "kb_scope": conv.kb_scope,
                    "created_at": conv.created_at.isoformat(),
                    "updated_at": conv.updated_at.isoformat(),
                }
                for conv in conversations
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
        },
    )


@router.post(
    "/conversations",
    summary="创建会话",
    description="创建新的对话会话。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse,
)
def create_conversation(
    request: Request,
    payload: ConversationCreateRequest,
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """创建新会话。"""
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.CHAT_COMPLETION,
    )

    # 验证知识库访问权限
    kb_ids = []
    if payload.kb_ids:
        from uuid import UUID as parse_uuid
        try:
            kb_ids = [parse_uuid(kb_id) for kb_id in payload.kb_ids]
        except (ValueError, AttributeError):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid kb_ids format")

        readable_kb_ids = filter_readable_kb_ids(
            db,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            kb_ids=kb_ids,
        )
        if not readable_kb_ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="no accessible knowledge bases")
        kb_ids = readable_kb_ids

    # 创建会话
    conversation = Conversation(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        title=payload.title,
        kb_scope={"kb_ids": [str(kb_id) for kb_id in kb_ids]} if kb_ids else {},
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)

    return success(
        request,
        {
            "conversation_id": str(conversation.id),
            "title": conversation.title,
            "kb_scope": conversation.kb_scope,
            "created_at": conversation.created_at.isoformat(),
            "updated_at": conversation.updated_at.isoformat(),
        },
    )


@router.get(
    "/conversations/{conversation_id}",
    summary="获取会话详情",
    description="获取指定会话的详细信息。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse,
)
def get_conversation(
    request: Request,
    conversation_id: UUID,
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """获取会话详情。"""
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.CHAT_COMPLETION,
    )

    conversation = db.get(Conversation, conversation_id)
    if (
        not conversation
        or conversation.tenant_id != ctx.tenant_id
        or conversation.user_id != ctx.user_id
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="conversation not found")

    # 统计消息数量
    message_count_stmt = (
        select(func.count(Message.id))
        .where(Message.conversation_id == conversation_id)
    )
    message_count = db.execute(message_count_stmt).scalar_one()

    return success(
        request,
        {
            "conversation_id": str(conversation.id),
            "title": conversation.title,
            "kb_scope": conversation.kb_scope,
            "message_count": message_count,
            "created_at": conversation.created_at.isoformat(),
            "updated_at": conversation.updated_at.isoformat(),
        },
    )


@router.get(
    "/conversations/{conversation_id}/messages",
    summary="获取会话消息历史",
    description="获取指定会话的所有消息记录。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse,
)
def get_conversation_messages(
    request: Request,
    conversation_id: UUID,
    limit: int = Query(default=100, ge=1, le=500, description="每页数量"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """获取会话消息历史。"""
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.CHAT_COMPLETION,
    )

    # 验证会话权限
    conversation = db.get(Conversation, conversation_id)
    if (
        not conversation
        or conversation.tenant_id != ctx.tenant_id
        or conversation.user_id != ctx.user_id
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="conversation not found")

    # 查询消息列表
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
        .limit(limit)
        .offset(offset)
    )
    result = db.execute(stmt)
    messages = result.scalars().all()

    # 统计总数
    count_stmt = (
        select(func.count(Message.id))
        .where(Message.conversation_id == conversation_id)
    )
    total = db.execute(count_stmt).scalar_one()

    return success(
        request,
        {
            "conversation_id": str(conversation_id),
            "messages": [
                {
                    "message_id": str(msg.id),
                    "role": msg.role,
                    "content": msg.content,
                    "citations": msg.citations,
                    "usage": msg.usage,
                    "created_at": msg.created_at.isoformat(),
                }
                for msg in messages
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
        },
    )


@router.patch(
    "/conversations/{conversation_id}",
    summary="更新会话",
    description="更新会话标题等信息。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse,
)
def update_conversation(
    request: Request,
    conversation_id: UUID,
    payload: ConversationUpdateRequest,
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """更新会话标题。"""
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.CHAT_COMPLETION,
    )

    conversation = db.get(Conversation, conversation_id)
    if (
        not conversation
        or conversation.tenant_id != ctx.tenant_id
        or conversation.user_id != ctx.user_id
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="conversation not found")

    conversation.title = payload.title
    db.commit()
    db.refresh(conversation)

    return success(
        request,
        {
            "conversation_id": str(conversation.id),
            "title": conversation.title,
            "created_at": conversation.created_at.isoformat(),
            "updated_at": conversation.updated_at.isoformat(),
        },
    )


@router.delete(
    "/conversations/{conversation_id}",
    summary="删除会话",
    description="删除指定会话及其所有消息。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse,
)
def delete_conversation(
    request: Request,
    conversation_id: UUID,
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """删除会话。"""
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.CHAT_COMPLETION,
    )

    conversation = db.get(Conversation, conversation_id)
    if (
        not conversation
        or conversation.tenant_id != ctx.tenant_id
        or conversation.user_id != ctx.user_id
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="conversation not found")

    # 删除会话（级联删除消息）
    db.delete(conversation)
    db.commit()

    return success(
        request,
        {
            "conversation_id": str(conversation_id),
            "deleted": True,
        },
    )


# ============ 对话补全 API ============


@router.post(
    "/completions",
    summary="创建问答回复（流式）",
    description="在授权知识库范围内检索并返回带引用的回答。支持会话上下文记忆和流式输出。",
    status_code=status.HTTP_200_OK,
)
async def chat_completions(
    payload: ChatCompletionRequest,
    request: Request,
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """保存会话消息并返回检索增强答案。"""
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.CHAT_COMPLETION,
    )
    if not payload.messages:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="messages required")

    # 先将客户端请求范围与服务端授权范围求交，杜绝越权知识库检索。
    readable_kb_ids = filter_readable_kb_ids(
        db,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        kb_ids=payload.kb_ids or None,
    )
    if payload.kb_ids and len(readable_kb_ids) != len(set(payload.kb_ids)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden kb scope")
    workspace_id = resolve_workspace_scope_for_kbs(
        db,
        tenant_id=ctx.tenant_id,
        kb_ids=readable_kb_ids,
    )
    estimated_tokens = max(1, min(len(payload.messages[-1].content) * 2, 4096))
    enforce_quota(
        db,
        tenant_id=ctx.tenant_id,
        metric_code=QuotaMetric.CHAT_TOKENS.value,
        projected_increment=estimated_tokens,
        workspace_id=workspace_id,
        actor_user_id=ctx.user_id,
    )

    conversation: Conversation | None
    if payload.conversation_id:
        # 指定会话 ID 时校验会话存在且属于当前租户。
        conversation = db.get(Conversation, payload.conversation_id)
        if (
            not conversation
            or conversation.tenant_id != ctx.tenant_id
            or conversation.user_id != ctx.user_id
        ):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="conversation not found")
    else:
        # 未指定会话则自动创建，首条问题用于生成标题。
        conversation = Conversation(
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            title=payload.messages[-1].content[:60],
            kb_scope={"kb_ids": [str(k) for k in readable_kb_ids]},
        )
        db.add(conversation)
        db.flush()

    question = payload.messages[-1].content

    # 加载会话历史上下文（短期记忆）
    context_messages = []
    if payload.conversation_id:
        # 获取最近 5 轮对话（10 条消息）
        history_stmt = (
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(desc(Message.created_at))
            .limit(10)
        )
        history_result = db.execute(history_stmt)
        history_messages = list(history_result.scalars().all())
        history_messages.reverse()  # 按时间正序

        # 格式化为上下文，过滤空消息
        for msg in history_messages:
            if msg.content and msg.content.strip():  # 只添加非空消息
                context_messages.append({
                    "role": msg.role,
                    "content": msg.content[:2000],  # 限制长度，避免超长消息
                })

    # 保存用户消息
    db.add(
        Message(
            tenant_id=ctx.tenant_id,
            conversation_id=UUID(str(conversation.id)),
            role=MessageRole.USER,
            content=question,
            citations=[],
            usage={},
        )
    )
    db.commit()

    # 保存会话ID和租户ID用于流式生成
    conversation_id = conversation.id
    tenant_id = ctx.tenant_id

    # 流式生成
    import json
    from tkp_api.services.rag.retrieval_improved import search_chunks_improved, RAGServicesSingleton

    async def generate_stream():
        # 创建新的数据库会话用于异步操作
        from tkp_api.db.session import SessionLocal
        stream_db = SessionLocal()

        try:
            # 先检索
            chunks = search_chunks_improved(
                stream_db,
                tenant_id=tenant_id,
                kb_ids=readable_kb_ids,
                query=question,
                top_k=6,
            )

            # 发送引用信息
            citations = []
            for chunk in chunks:
                citations.append({
                    "chunk_id": str(chunk["chunk_id"]),
                    "document_id": str(chunk["document_id"]),
                    "document_version_id": str(chunk.get("document_version_id", "")),
                    "document_title": chunk["document_title"],
                    "kb_name": chunk["kb_name"],
                    "similarity": chunk["similarity"],
                    "snippet": chunk.get("snippet", ""),
                    "content": chunk["content"],
                })

            yield f"data: {json.dumps({'type': 'citations', 'data': citations}, ensure_ascii=False)}\n\n"

            # 流式生成回答
            generator = RAGServicesSingleton.get_generator()
            full_answer = ""

            import logging
            logger = logging.getLogger("tkp_api.chat")
            logger.info(f"Starting streaming generation for question: {question[:50]}...")

            chunk_count = 0
            for chunk_text in generator.generate_streaming_answer(
                query=question,
                context_chunks=chunks,
                history_messages=context_messages,
            ):
                chunk_count += 1
                full_answer += chunk_text
                logger.debug(f"Received chunk {chunk_count}: {chunk_text[:50]}...")
                yield f"data: {json.dumps({'type': 'content', 'data': chunk_text}, ensure_ascii=False)}\n\n"

            logger.info(f"Streaming completed. Total chunks: {chunk_count}, answer length: {len(full_answer)}")

            # 保存助手消息
            assistant_message = Message(
                tenant_id=tenant_id,
                conversation_id=UUID(str(conversation_id)),
                role=MessageRole.ASSISTANT,
                content=full_answer,
                citations=citations,
                usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            )
            stream_db.add(assistant_message)
            stream_db.commit()

            # 发送完成信号
            yield f"data: {json.dumps({'type': 'done', 'data': {'message_id': str(assistant_message.id), 'conversation_id': str(conversation_id)}}, ensure_ascii=False)}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'data': str(e)}, ensure_ascii=False)}\n\n"
        finally:
            stream_db.close()

    return StreamingResponse(generate_stream(), media_type="text/event-stream")
