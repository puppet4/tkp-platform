"""智能体运行任务接口。"""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from sqlalchemy.orm import Session

from tkp_api.dependencies import get_request_context
from tkp_api.db.session import get_db
from tkp_api.models.agent import AgentRun
from tkp_api.models.conversation import Conversation
from tkp_api.models.enums import AgentRunStatus
from tkp_api.utils.response import success
from tkp_api.schemas.agent import AgentRunCreateRequest
from tkp_api.schemas.common import ErrorResponse, SuccessResponse
from tkp_api.schemas.responses import AgentRunData, AgentRunDetailData
from tkp_api.services import PermissionAction, audit_log, require_tenant_action

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post(
    "/runs",
    summary="创建智能体任务",
    description="创建异步智能体运行任务，并记录审计日志。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[AgentRunData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def create_agent_run(
    payload: AgentRunCreateRequest,
    request: Request,
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """创建智能体运行记录。"""
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.AGENT_RUN_CREATE,
    )
    if payload.conversation_id:
        conversation = db.get(Conversation, payload.conversation_id)
        if (
            not conversation
            or conversation.tenant_id != ctx.tenant_id
            or conversation.user_id != ctx.user_id
        ):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="conversation not found")

    # 任务初始化为 queued，后续由异步执行器推进状态。
    run = AgentRun(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        conversation_id=payload.conversation_id,
        plan_json={"task": payload.task, "kb_ids": [str(k) for k in payload.kb_ids]},
        tool_calls=[],
        status=AgentRunStatus.QUEUED,
    )
    db.add(run)
    db.flush()

    audit_log(
        db=db,
        request=request,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        action="agent.run.create",
        resource_type="agent_run",
        resource_id=str(run.id),
        after_json={"conversation_id": str(payload.conversation_id) if payload.conversation_id else None},
    )

    db.commit()
    return success(request, {"run_id": run.id, "status": run.status})


@router.get(
    "/runs/{run_id}",
    summary="查询智能体任务",
    description="按任务 ID 返回智能体运行详情与当前状态。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[AgentRunDetailData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def get_agent_run(
    request: Request,
    run_id: UUID = Path(..., description="智能体任务 ID。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """查询单个智能体运行任务。"""
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.AGENT_RUN_READ,
    )
    run = db.get(AgentRun, run_id)
    if not run or run.tenant_id != ctx.tenant_id or run.user_id != ctx.user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")

    return success(
        request,
        {
            "run_id": run.id,
            "status": run.status,
            "plan_json": run.plan_json,
            "tool_calls": run.tool_calls,
            "cost": float(run.cost),
            "started_at": run.started_at,
            "finished_at": run.finished_at,
        },
    )


@router.post(
    "/runs/{run_id}/cancel",
    summary="取消智能体任务",
    description="取消可变状态任务（queued/running），并写入审计日志。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[AgentRunData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def cancel_agent_run(
    request: Request,
    run_id: UUID = Path(..., description="智能体任务 ID。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """取消智能体任务。"""
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.AGENT_RUN_CANCEL,
    )
    run = db.get(AgentRun, run_id)
    if not run or run.tenant_id != ctx.tenant_id or run.user_id != ctx.user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")

    before = {"status": run.status}
    # 仅允许取消可变状态任务，终态任务保持原样。
    if run.status in {AgentRunStatus.QUEUED, AgentRunStatus.RUNNING}:
        run.status = AgentRunStatus.CANCELED
        run.finished_at = datetime.now(timezone.utc)

    audit_log(
        db=db,
        request=request,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        action="agent.run.cancel",
        resource_type="agent_run",
        resource_id=str(run.id),
        before_json=before,
        after_json={"status": run.status},
    )

    db.commit()

    return success(request, {"run_id": run.id, "status": run.status})
