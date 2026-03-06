"""用户反馈 API。"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from tkp_api.db.session import get_db
from tkp_api.dependencies import require_tenant_roles
from tkp_api.models.enums import TenantRole
from tkp_api.schemas.common import SuccessResponse
from tkp_api.services.feedback_replay import FeedbackReplayService
from tkp_api.utils.response import success

router = APIRouter(prefix="/feedback", tags=["feedback"])


class FeedbackCreateRequest(BaseModel):
    """创建反馈请求。"""

    feedback_type: str = Field(description="反馈类型（thumbs_up/thumbs_down/rating/comment）")
    feedback_value: str | None = Field(default=None, description="反馈值")
    comment: str | None = Field(default=None, description="评论")
    tags: list[str] | None = Field(default=None, description="标签")
    conversation_id: UUID | None = Field(default=None, description="会话 ID")
    message_id: UUID | None = Field(default=None, description="消息 ID")
    retrieval_log_id: UUID | None = Field(default=None, description="检索日志 ID")


class FeedbackReplayRequest(BaseModel):
    """反馈回放请求。"""

    feedback_id: UUID = Field(description="反馈 ID")
    replay_type: str = Field(default="full_pipeline", description="回放类型（retrieval/generation/full_pipeline）")


@router.post(
    "",
    summary="提交用户反馈",
    description="收集用户对检索或生成结果的反馈。",
    status_code=status.HTTP_201_CREATED,
    response_model=SuccessResponse,
)
def create_feedback(
    request: Request,
    payload: FeedbackCreateRequest,
    db: Session = Depends(get_db),
    ctx=Depends(require_tenant_roles([TenantRole.MEMBER])),
):
    """提交用户反馈。"""
    service = FeedbackReplayService()

    feedback = service.collect_feedback(
        db,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        feedback_type=payload.feedback_type,
        feedback_value=payload.feedback_value,
        comment=payload.comment,
        tags=payload.tags,
        conversation_id=payload.conversation_id,
        message_id=payload.message_id,
        retrieval_log_id=payload.retrieval_log_id,
    )

    return success(
        request,
        {
            "feedback_id": str(feedback.id),
            "feedback_type": feedback.feedback_type,
            "created_at": feedback.created_at.isoformat(),
        },
    )


@router.post(
    "/replay",
    summary="回放反馈",
    description="基于用户反馈回放检索或生成流程，用于质量分析和改进。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse,
)
def replay_feedback(
    request: Request,
    payload: FeedbackReplayRequest,
    db: Session = Depends(get_db),
    ctx=Depends(require_tenant_roles([TenantRole.ADMIN])),
):
    """回放反馈。"""
    service = FeedbackReplayService()

    try:
        replay = service.replay_feedback(
            db,
            feedback_id=payload.feedback_id,
            replay_type=payload.replay_type,
        )

        return success(
            request,
            {
                "replay_id": str(replay.id),
                "status": replay.status,
                "comparison": replay.comparison,
                "suggestions": replay.suggestions,
                "completed_at": replay.completed_at.isoformat() if replay.completed_at else None,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get(
    "/replay/{replay_id}",
    summary="获取回放结果",
    description="获取反馈回放的详细结果。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse,
)
def get_replay_result(
    request: Request,
    replay_id: UUID,
    db: Session = Depends(get_db),
    ctx=Depends(require_tenant_roles([TenantRole.ADMIN])),
):
    """获取回放结果。"""
    from sqlalchemy import select
    from tkp_api.models.feedback import FeedbackReplay

    stmt = select(FeedbackReplay).where(
        FeedbackReplay.id == replay_id,
        FeedbackReplay.tenant_id == ctx.tenant_id,
    )
    result = db.execute(stmt)
    replay = result.scalar_one_or_none()

    if not replay:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="replay not found")

    return success(
        request,
        {
            "replay_id": str(replay.id),
            "feedback_id": str(replay.feedback_id),
            "replay_type": replay.replay_type,
            "status": replay.status,
            "original_result": replay.original_result,
            "replay_result": replay.replay_result,
            "comparison": replay.comparison,
            "suggestions": replay.suggestions,
            "error_message": replay.error_message,
            "created_at": replay.created_at.isoformat(),
            "completed_at": replay.completed_at.isoformat() if replay.completed_at else None,
        },
    )


@router.get(
    "",
    summary="获取反馈列表",
    description="获取租户的用户反馈列表。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse,
)
def list_feedbacks(
    request: Request,
    processed: bool | None = None,
    feedback_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    ctx=Depends(require_tenant_roles([TenantRole.ADMIN])),
):
    """获取反馈列表。"""
    from sqlalchemy import select
    from tkp_api.models.feedback import UserFeedback

    stmt = select(UserFeedback).where(UserFeedback.tenant_id == ctx.tenant_id)

    if processed is not None:
        stmt = stmt.where(UserFeedback.processed == processed)

    if feedback_type:
        stmt = stmt.where(UserFeedback.feedback_type == feedback_type)

    stmt = stmt.order_by(UserFeedback.created_at.desc()).limit(limit).offset(offset)

    result = db.execute(stmt)
    feedbacks = result.scalars().all()

    return success(
        request,
        {
            "feedbacks": [
                {
                    "feedback_id": str(f.id),
                    "user_id": str(f.user_id),
                    "feedback_type": f.feedback_type,
                    "feedback_value": f.feedback_value,
                    "comment": f.comment,
                    "tags": f.tags,
                    "processed": f.processed,
                    "created_at": f.created_at.isoformat(),
                }
                for f in feedbacks
            ],
            "total": len(feedbacks),
            "limit": limit,
            "offset": offset,
        },
    )
