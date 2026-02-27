"""领域枚举定义。"""

from enum import StrEnum


class TenantStatus(StrEnum):
    """租户状态。"""

    ACTIVE = "active"  # 正常可用，可访问租户下资源。
    SUSPENDED = "suspended"  # 暂停状态，通常禁止继续写入。
    DELETED = "deleted"  # 逻辑删除状态，仅用于审计与保留。


class MembershipStatus(StrEnum):
    """成员关系状态。"""

    ACTIVE = "active"  # 已生效成员，可按角色访问资源。
    INVITED = "invited"  # 邀请中，尚未完成激活。
    DISABLED = "disabled"  # 已禁用，不再参与权限判断。


class TenantRole(StrEnum):
    """租户角色。"""

    OWNER = "owner"  # 租户所有者，具备最高管理权限。
    ADMIN = "admin"  # 租户管理员，可管理成员与主要配置。
    MEMBER = "member"  # 普通成员，具备基础协作权限。
    VIEWER = "viewer"  # 只读成员，仅可查看授权资源。


class WorkspaceStatus(StrEnum):
    """工作空间状态。"""

    ACTIVE = "active"  # 工作空间正常可用。
    ARCHIVED = "archived"  # 已归档，通常限制新增/修改操作。


class WorkspaceRole(StrEnum):
    """工作空间角色。"""

    OWNER = "ws_owner"  # 工作空间所有者。
    EDITOR = "ws_editor"  # 可编辑工作空间内资源。
    VIEWER = "ws_viewer"  # 仅可读工作空间内资源。


class KBStatus(StrEnum):
    """知识库状态。"""

    ACTIVE = "active"  # 知识库可正常检索与维护。
    ARCHIVED = "archived"  # 知识库归档，通常停止更新。


class KBRole(StrEnum):
    """知识库角色。"""

    OWNER = "kb_owner"  # 知识库所有者。
    EDITOR = "kb_editor"  # 可维护文档与配置。
    VIEWER = "kb_viewer"  # 仅可读取知识库内容。


class DocumentStatus(StrEnum):
    """文档状态。"""

    PENDING = "pending"  # 已创建，等待处理。
    PROCESSING = "processing"  # 正在解析/切片/向量化。
    READY = "ready"  # 处理完成，可用于检索。
    FAILED = "failed"  # 处理失败，需人工排查或重试。
    DELETED = "deleted"  # 逻辑删除，不再出现在业务查询中。


class ParseStatus(StrEnum):
    """文档解析状态。"""

    PENDING = "pending"  # 解析任务待执行。
    SUCCESS = "success"  # 解析成功。
    FAILED = "failed"  # 解析失败。


class SourceType(StrEnum):
    """文档来源类型。"""

    UPLOAD = "upload"  # 用户上传文件。
    URL = "url"  # 外部链接抓取。
    NOTION = "notion"  # Notion 数据源同步。
    GIT = "git"  # Git 仓库导入。


class MessageRole(StrEnum):
    """会话消息角色。"""

    USER = "user"  # 用户输入消息。
    ASSISTANT = "assistant"  # 模型生成回复。
    TOOL = "tool"  # 工具调用或工具返回消息。
    SYSTEM = "system"  # 系统级指令或约束消息。


class AgentRunStatus(StrEnum):
    """智能体任务状态。"""

    QUEUED = "queued"  # 已入队，等待调度执行。
    RUNNING = "running"  # 任务执行中。
    SUCCESS = "success"  # 执行成功结束。
    FAILED = "failed"  # 执行失败结束。
    BLOCKED = "blocked"  # 因权限/依赖阻塞，无法继续。
    CANCELED = "canceled"  # 被主动取消。


class IngestionJobStatus(StrEnum):
    """入库任务状态。"""

    QUEUED = "queued"  # 已创建，等待消费。
    PROCESSING = "processing"  # 任务处理中。
    RETRYING = "retrying"  # 失败后重试中。
    COMPLETED = "completed"  # 处理完成。
    DEAD_LETTER = "dead_letter"  # 超过重试上限，进入死信。
