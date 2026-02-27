"""多层权限校验服务。

统一封装租户、工作空间、知识库、文档的读写权限判断，
避免路由层重复拼装授权 SQL 导致规则不一致。
"""

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from tkp_api.models.enums import DocumentStatus, KBRole, KBStatus, MembershipStatus, WorkspaceRole, WorkspaceStatus
from tkp_api.models.knowledge import Document, KBMembership, KnowledgeBase
from tkp_api.models.workspace import Workspace, WorkspaceMembership

# 工作空间写权限角色集合。
WORKSPACE_WRITE_ROLES = {WorkspaceRole.OWNER, WorkspaceRole.EDITOR}
# 知识库写权限角色集合。
KB_WRITE_ROLES = {KBRole.OWNER, KBRole.EDITOR}


def _forbidden() -> HTTPException:
    """统一 403 异常。"""
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")


def _not_found(message: str) -> HTTPException:
    """统一 404 异常。"""
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)


def get_workspace_membership(
    db: Session,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    user_id: UUID,
) -> WorkspaceMembership | None:
    """查询用户在工作空间中的有效成员关系。"""
    return (
        db.execute(
            select(WorkspaceMembership)
            .where(WorkspaceMembership.tenant_id == tenant_id)
            .where(WorkspaceMembership.workspace_id == workspace_id)
            .where(WorkspaceMembership.user_id == user_id)
            .where(WorkspaceMembership.status == MembershipStatus.ACTIVE)
        )
        .scalar_one_or_none()
    )


def ensure_workspace_read_access(
    db: Session,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    user_id: UUID,
) -> tuple[Workspace, WorkspaceMembership]:
    """校验工作空间读权限。

    判定规则：
    1. 工作空间必须存在且属于当前租户。
    2. 当前用户必须在该工作空间存在 active 成员关系。
    """
    workspace = db.get(Workspace, workspace_id)
    if not workspace or workspace.tenant_id != tenant_id:
        raise _not_found("workspace not found")
    if workspace.status == WorkspaceStatus.ARCHIVED:
        raise _not_found("workspace not found")

    membership = get_workspace_membership(
        db,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        user_id=user_id,
    )
    if not membership:
        raise _forbidden()

    return workspace, membership


def ensure_workspace_write_access(
    db: Session,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    user_id: UUID,
) -> tuple[Workspace, WorkspaceMembership]:
    """校验工作空间写权限。"""
    workspace, membership = ensure_workspace_read_access(
        db,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        user_id=user_id,
    )
    if membership.role not in WORKSPACE_WRITE_ROLES:
        raise _forbidden()
    return workspace, membership


def get_kb_membership(db: Session, *, tenant_id: UUID, kb_id: UUID, user_id: UUID) -> KBMembership | None:
    """查询用户在知识库中的成员关系。"""
    return (
        db.execute(
            select(KBMembership)
            .where(KBMembership.tenant_id == tenant_id)
            .where(KBMembership.kb_id == kb_id)
            .where(KBMembership.user_id == user_id)
            .where(KBMembership.status == MembershipStatus.ACTIVE)
        )
        .scalar_one_or_none()
    )


def ensure_kb_read_access(
    db: Session,
    *,
    tenant_id: UUID,
    kb_id: UUID,
    user_id: UUID,
) -> tuple[KnowledgeBase, WorkspaceMembership, KBMembership]:
    """校验知识库读权限（工作空间成员 + 知识库成员）。

    为什么要双重校验：
    1. 工作空间成员关系定义了协作边界。
    2. 知识库成员关系定义了更细粒度授权。
    两者都满足才允许读取知识库内容。
    """
    kb = db.get(KnowledgeBase, kb_id)
    if not kb or kb.tenant_id != tenant_id:
        raise _not_found("knowledge base not found")
    if kb.status == KBStatus.ARCHIVED:
        raise _not_found("knowledge base not found")

    _, ws_membership = ensure_workspace_read_access(
        db,
        tenant_id=tenant_id,
        workspace_id=kb.workspace_id,
        user_id=user_id,
    )

    kb_membership = get_kb_membership(db, tenant_id=tenant_id, kb_id=kb.id, user_id=user_id)
    if not kb_membership:
        raise _forbidden()

    return kb, ws_membership, kb_membership


def ensure_kb_write_access(
    db: Session,
    *,
    tenant_id: UUID,
    kb_id: UUID,
    user_id: UUID,
) -> tuple[KnowledgeBase, WorkspaceMembership, KBMembership | None]:
    """校验知识库写权限。

    放行规则：
    1) 工作空间角色是 owner/editor；或
    2) 知识库角色是 kb_owner/kb_editor。
    """
    kb = db.get(KnowledgeBase, kb_id)
    if not kb or kb.tenant_id != tenant_id:
        raise _not_found("knowledge base not found")
    if kb.status == KBStatus.ARCHIVED:
        raise _not_found("knowledge base not found")

    _, ws_membership = ensure_workspace_read_access(
        db,
        tenant_id=tenant_id,
        workspace_id=kb.workspace_id,
        user_id=user_id,
    )

    kb_membership = get_kb_membership(db, tenant_id=tenant_id, kb_id=kb.id, user_id=user_id)

    # 工作空间高权限角色可直接写知识库。
    if ws_membership.role in WORKSPACE_WRITE_ROLES:
        return kb, ws_membership, kb_membership

    # 否则要求显式拥有知识库写角色。
    if kb_membership and kb_membership.role in KB_WRITE_ROLES:
        return kb, ws_membership, kb_membership

    raise _forbidden()


def ensure_document_read_access(
    db: Session,
    *,
    tenant_id: UUID,
    document_id: UUID,
    user_id: UUID,
) -> tuple[Document, KnowledgeBase]:
    """校验文档读权限（文档 -> 知识库 -> 工作空间）。"""
    document = db.get(Document, document_id)
    if not document or document.tenant_id != tenant_id:
        raise _not_found("document not found")
    if document.status == DocumentStatus.DELETED:
        raise _not_found("document not found")

    kb, _, _ = ensure_kb_read_access(
        db,
        tenant_id=tenant_id,
        kb_id=document.kb_id,
        user_id=user_id,
    )
    return document, kb


def filter_readable_kb_ids(
    db: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    kb_ids: list[UUID] | None,
) -> list[UUID]:
    """按当前用户权限过滤可读知识库集合。

    用于检索与问答场景，确保即使客户端传入越权 kb_id，
    最终执行范围仍严格受服务端授权约束。
    """
    ws_memberships = (
        db.execute(
            select(WorkspaceMembership)
            .where(WorkspaceMembership.tenant_id == tenant_id)
            .where(WorkspaceMembership.user_id == user_id)
            .where(WorkspaceMembership.status == MembershipStatus.ACTIVE)
        )
        .scalars()
        .all()
    )
    readable_workspace_ids = list({membership.workspace_id for membership in ws_memberships})
    if not readable_workspace_ids:
        return []

    kb_membership_stmt = (
        select(KBMembership.kb_id)
        .where(KBMembership.user_id == user_id)
        .where(KBMembership.tenant_id == tenant_id)
        .where(KBMembership.status == MembershipStatus.ACTIVE)
    )

    # 如果客户端指定了 kb_ids，则在知识库成员范围上先做交集过滤。
    if kb_ids:
        kb_membership_stmt = kb_membership_stmt.where(KBMembership.kb_id.in_(kb_ids))

    readable_kb_ids = db.execute(kb_membership_stmt).scalars().all()
    if not readable_kb_ids:
        return []

    rows = (
        db.execute(
            select(KnowledgeBase.id)
            .where(KnowledgeBase.tenant_id == tenant_id)
            .where(KnowledgeBase.status == KBStatus.ACTIVE)
            .where(KnowledgeBase.workspace_id.in_(readable_workspace_ids))
            .where(KnowledgeBase.id.in_(readable_kb_ids))
        )
        .scalars()
        .all()
    )
    return rows
