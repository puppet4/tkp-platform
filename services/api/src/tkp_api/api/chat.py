"""问答接口。"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from tkp_api.dependencies import get_request_context
from tkp_api.db.session import get_db
from tkp_api.models.conversation import Conversation, Message
from tkp_api.models.enums import MessageRole
from tkp_api.utils.response import success
from tkp_api.schemas.chat import ChatCompletionRequest
from tkp_api.schemas.common import ErrorResponse, SuccessResponse
from tkp_api.schemas.responses import ChatCompletionData
from tkp_api.services import PermissionAction, filter_readable_kb_ids, require_tenant_action, search_chunks

router = APIRouter(prefix="/chat", tags=["chat"])


def _compose_answer(question: str, hits: list[dict[str, object]]) -> str:
    """根据检索结果拼装可复现答案，便于联调验证。"""
    if not hits:
        return f"未检索到与问题“{question}”相关的知识片段。"

    bullet_lines = [f"- {hit['snippet']}" for hit in hits[:3]]
    return "基于知识库检索到以下信息:\n" + "\n".join(bullet_lines)


@router.post(
    "/completions",
    summary="创建问答回复",
    description="在授权知识库范围内检索并返回带引用的回答。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[ChatCompletionData],
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
def chat_completions(
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
    db.add(
        Message(
            tenant_id=ctx.tenant_id,
            conversation_id=conversation.id,
            role=MessageRole.USER,
            content=question,
            citations=[],
            usage={},
        )
    )

    hits = search_chunks(
        db,
        tenant_id=ctx.tenant_id,
        kb_ids=readable_kb_ids,
        query=question,
        top_k=6,
    )
    answer_text = _compose_answer(question, hits)

    # 引用信息用于前端可追溯展示“答案来自哪些切片”。
    citations = [
        {
            "document_id": hit["document_id"],
            "chunk_id": hit["chunk_id"],
            "document_version_id": hit["document_version_id"],
        }
        for hit in hits
    ]

    # 这里使用简化 token 估算，后续可替换为真实 tokenizer 统计。
    prompt_tokens = max(1, len(question.split()))
    completion_tokens = max(1, len(answer_text.split()))

    assistant_message = Message(
        tenant_id=ctx.tenant_id,
        conversation_id=conversation.id,
        role=MessageRole.ASSISTANT,
        content=answer_text,
        citations=citations,
        usage={
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    )
    db.add(assistant_message)
    db.commit()

    return success(
        request,
        {
            "message_id": assistant_message.id,
            "answer": answer_text,
            "citations": citations,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            "conversation_id": conversation.id,
        },
    )
