"""Agent 恢复点服务。

提供 Agent 执行恢复点功能：
- 创建恢复点
- 恢复执行
- 状态管理
"""

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from tkp_api.models.agent import AgentRun
from tkp_api.models.agent_checkpoint import AgentCheckpoint, AgentRecovery

logger = logging.getLogger("tkp_api.agent_checkpoint")


class AgentCheckpointService:
    """Agent 恢复点服务。"""

    def create_checkpoint(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        agent_run_id: UUID,
        checkpoint_type: str,
        state_snapshot: dict[str, Any],
        completed_steps: list[str],
        pending_steps: list[str],
        context_data: dict[str, Any],
        tool_call_history: list[dict[str, Any]],
        error_info: dict[str, Any] | None = None,
        recoverable: bool = True,
        recovery_strategy: str | None = None,
        notes: str | None = None,
    ) -> AgentCheckpoint:
        """创建恢复点。

        Args:
            db: 数据库会话
            tenant_id: 租户 ID
            agent_run_id: Agent 运行 ID
            checkpoint_type: 恢复点类型（step_completed/tool_executed/error_occurred/manual）
            state_snapshot: 状态快照
            completed_steps: 已完成步骤
            pending_steps: 待执行步骤
            context_data: 上下文数据
            tool_call_history: 工具调用历史
            error_info: 错误信息
            recoverable: 是否可恢复
            recovery_strategy: 恢复策略
            notes: 备注

        Returns:
            恢复点对象
        """
        # 获取当前恢复点序号
        stmt = (
            select(AgentCheckpoint)
            .where(AgentCheckpoint.agent_run_id == agent_run_id)
            .order_by(AgentCheckpoint.checkpoint_seq.desc())
        )
        result = db.execute(stmt)
        last_checkpoint = result.scalars().first()

        checkpoint_seq = (last_checkpoint.checkpoint_seq + 1) if last_checkpoint else 0

        # 创建恢复点
        checkpoint = AgentCheckpoint(
            tenant_id=tenant_id,
            agent_run_id=agent_run_id,
            checkpoint_seq=checkpoint_seq,
            checkpoint_type=checkpoint_type,
            state_snapshot=state_snapshot,
            completed_steps=completed_steps,
            pending_steps=pending_steps,
            context_data=context_data,
            tool_call_history=tool_call_history,
            error_info=error_info,
            recoverable=recoverable,
            recovery_strategy=recovery_strategy,
            notes=notes,
        )

        db.add(checkpoint)
        db.commit()
        db.refresh(checkpoint)

        logger.info(
            "checkpoint created: id=%s, run_id=%s, seq=%d, type=%s",
            checkpoint.id,
            agent_run_id,
            checkpoint_seq,
            checkpoint_type,
        )

        return checkpoint

    def get_latest_checkpoint(
        self,
        db: Session,
        *,
        agent_run_id: UUID,
        recoverable_only: bool = True,
    ) -> AgentCheckpoint | None:
        """获取最新的恢复点。

        Args:
            db: 数据库会话
            agent_run_id: Agent 运行 ID
            recoverable_only: 是否只返回可恢复的恢复点

        Returns:
            恢复点对象或 None
        """
        stmt = (
            select(AgentCheckpoint)
            .where(AgentCheckpoint.agent_run_id == agent_run_id)
            .order_by(AgentCheckpoint.checkpoint_seq.desc())
        )

        if recoverable_only:
            stmt = stmt.where(AgentCheckpoint.recoverable == True)

        result = db.execute(stmt)
        return result.scalars().first()

    def list_checkpoints(
        self,
        db: Session,
        *,
        agent_run_id: UUID,
        checkpoint_type: str | None = None,
    ) -> list[AgentCheckpoint]:
        """列出所有恢复点。

        Args:
            db: 数据库会话
            agent_run_id: Agent 运行 ID
            checkpoint_type: 恢复点类型过滤

        Returns:
            恢复点列表
        """
        stmt = (
            select(AgentCheckpoint)
            .where(AgentCheckpoint.agent_run_id == agent_run_id)
            .order_by(AgentCheckpoint.checkpoint_seq.asc())
        )

        if checkpoint_type:
            stmt = stmt.where(AgentCheckpoint.checkpoint_type == checkpoint_type)

        result = db.execute(stmt)
        return list(result.scalars().all())

    def recover_from_checkpoint(
        self,
        db: Session,
        *,
        checkpoint_id: UUID,
        recovery_strategy: str = "resume",
        agent_executor=None,
    ) -> AgentRecovery:
        """从恢复点恢复执行。

        Args:
            db: 数据库会话
            checkpoint_id: 恢复点 ID
            recovery_strategy: 恢复策略（resume/retry/skip/abort）
            agent_executor: Agent 执行器

        Returns:
            恢复记录
        """
        # 获取恢复点
        stmt = select(AgentCheckpoint).where(AgentCheckpoint.id == checkpoint_id)
        result = db.execute(stmt)
        checkpoint = result.scalar_one_or_none()

        if not checkpoint:
            raise ValueError(f"checkpoint not found: {checkpoint_id}")

        if not checkpoint.recoverable:
            raise ValueError(f"checkpoint is not recoverable: {checkpoint_id}")

        # 创建恢复记录
        recovery = AgentRecovery(
            tenant_id=checkpoint.tenant_id,
            agent_run_id=checkpoint.agent_run_id,
            checkpoint_id=checkpoint_id,
            status="running",
            recovery_strategy=recovery_strategy,
            before_state=checkpoint.state_snapshot,
        )

        db.add(recovery)
        db.commit()
        db.refresh(recovery)

        try:
            # 执行恢复
            if recovery_strategy == "resume":
                recovery_result = self._resume_execution(db, checkpoint, agent_executor)
            elif recovery_strategy == "retry":
                recovery_result = self._retry_execution(db, checkpoint, agent_executor)
            elif recovery_strategy == "skip":
                recovery_result = self._skip_and_continue(db, checkpoint, agent_executor)
            elif recovery_strategy == "abort":
                recovery_result = self._abort_execution(db, checkpoint)
            else:
                raise ValueError(f"unsupported recovery strategy: {recovery_strategy}")

            # 更新恢复记录
            recovery.status = "completed"
            recovery.after_state = recovery_result.get("after_state")
            recovery.recovery_result = recovery_result
            recovery.completed_at = datetime.now(timezone.utc)

            db.commit()
            db.refresh(recovery)

            logger.info(
                "recovery completed: id=%s, checkpoint_id=%s, strategy=%s",
                recovery.id,
                checkpoint_id,
                recovery_strategy,
            )

            return recovery

        except Exception as exc:
            logger.exception("recovery failed: %s", exc)
            recovery.status = "failed"
            recovery.error_message = str(exc)
            recovery.completed_at = datetime.now(timezone.utc)
            db.commit()
            raise

    def _resume_execution(
        self,
        db: Session,
        checkpoint: AgentCheckpoint,
        agent_executor,
    ) -> dict[str, Any]:
        """恢复执行（从中断点继续）。"""
        logger.info("resuming execution from checkpoint %s", checkpoint.id)

        # 恢复上下文
        context = checkpoint.context_data.copy()
        pending_steps = checkpoint.pending_steps.copy()

        # 如果有 agent_executor，继续执行待处理步骤
        if agent_executor and pending_steps:
            result = agent_executor.execute_steps(
                steps=pending_steps,
                context=context,
                tool_call_history=checkpoint.tool_call_history,
            )
            return {
                "strategy": "resume",
                "completed_steps": checkpoint.completed_steps + result.get("completed_steps", []),
                "after_state": result.get("final_state"),
                "execution_result": result,
            }

        return {
            "strategy": "resume",
            "completed_steps": checkpoint.completed_steps,
            "after_state": checkpoint.state_snapshot,
            "message": "no executor provided, state restored only",
        }

    def _retry_execution(
        self,
        db: Session,
        checkpoint: AgentCheckpoint,
        agent_executor,
    ) -> dict[str, Any]:
        """重试执行（重新执行失败的步骤）。"""
        logger.info("retrying execution from checkpoint %s", checkpoint.id)

        if not checkpoint.error_info:
            raise ValueError("no error info in checkpoint, cannot retry")

        # 获取失败的步骤
        failed_step = checkpoint.error_info.get("failed_step")
        if not failed_step:
            raise ValueError("no failed step info in checkpoint")

        # 重试失败的步骤
        if agent_executor:
            result = agent_executor.execute_steps(
                steps=[failed_step] + checkpoint.pending_steps,
                context=checkpoint.context_data,
                tool_call_history=checkpoint.tool_call_history,
            )
            return {
                "strategy": "retry",
                "retried_step": failed_step,
                "completed_steps": checkpoint.completed_steps + result.get("completed_steps", []),
                "after_state": result.get("final_state"),
                "execution_result": result,
            }

        return {
            "strategy": "retry",
            "retried_step": failed_step,
            "message": "no executor provided, cannot retry",
        }

    def _skip_and_continue(
        self,
        db: Session,
        checkpoint: AgentCheckpoint,
        agent_executor,
    ) -> dict[str, Any]:
        """跳过失败步骤，继续执行。"""
        logger.info("skipping failed step and continuing from checkpoint %s", checkpoint.id)

        # 跳过第一个待处理步骤，继续执行剩余步骤
        remaining_steps = checkpoint.pending_steps[1:] if checkpoint.pending_steps else []

        if agent_executor and remaining_steps:
            result = agent_executor.execute_steps(
                steps=remaining_steps,
                context=checkpoint.context_data,
                tool_call_history=checkpoint.tool_call_history,
            )
            return {
                "strategy": "skip",
                "skipped_step": checkpoint.pending_steps[0] if checkpoint.pending_steps else None,
                "completed_steps": checkpoint.completed_steps + result.get("completed_steps", []),
                "after_state": result.get("final_state"),
                "execution_result": result,
            }

        return {
            "strategy": "skip",
            "skipped_step": checkpoint.pending_steps[0] if checkpoint.pending_steps else None,
            "message": "no remaining steps or no executor provided",
        }

    def _abort_execution(
        self,
        db: Session,
        checkpoint: AgentCheckpoint,
    ) -> dict[str, Any]:
        """中止执行。"""
        logger.info("aborting execution at checkpoint %s", checkpoint.id)

        # 更新 Agent Run 状态为 failed
        stmt = select(AgentRun).where(AgentRun.id == checkpoint.agent_run_id)
        result = db.execute(stmt)
        agent_run = result.scalar_one_or_none()

        if agent_run:
            agent_run.status = "failed"
            agent_run.finished_at = datetime.now(timezone.utc)
            db.commit()

        return {
            "strategy": "abort",
            "completed_steps": checkpoint.completed_steps,
            "aborted_at_seq": checkpoint.checkpoint_seq,
            "message": "execution aborted",
        }
