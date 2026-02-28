"""权限管理相关请求结构。"""

from pydantic import BaseModel, Field, field_validator


class RolePermissionUpdateRequest(BaseModel):
    """租户角色权限点更新请求。"""

    permission_codes: list[str] = Field(
        default_factory=list,
        description="角色权限点编码列表，支持 api/menu/button/feature 等前缀。",
        examples=[["api.user.read", "api.user.update", "menu.user", "button.user.delete"]],
    )

    @field_validator("permission_codes")
    @classmethod
    def normalize_codes(cls, value: list[str]) -> list[str]:
        """规范化权限编码并去重。"""
        normalized = []
        seen = set()
        for item in value:
            code = item.strip()
            if not code:
                continue
            if code in seen:
                continue
            seen.add(code)
            normalized.append(code)
        return normalized


class PermissionTemplatePublishRequest(BaseModel):
    """权限模板发布请求。"""

    overwrite_existing: bool = Field(
        default=True,
        description="是否覆盖当前租户角色已有权限配置；false 表示仅填充未配置角色。",
    )
