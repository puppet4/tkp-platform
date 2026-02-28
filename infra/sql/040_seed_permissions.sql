-- 为“尚未配置权限”的租户角色写入默认权限点。
-- 规则：同一 tenant+role 已有任意权限点时，不做覆盖。

WITH role_defaults(role, permission_code) AS (
    VALUES
        -- owner: 全量 API + 全量 UI 权限
        ('owner', 'api.tenant.read'),
        ('owner', 'api.tenant.update'),
        ('owner', 'api.tenant.delete'),
        ('owner', 'api.tenant.member.manage'),
        ('owner', 'api.user.read'),
        ('owner', 'api.user.update'),
        ('owner', 'api.workspace.create'),
        ('owner', 'api.workspace.read'),
        ('owner', 'api.workspace.update'),
        ('owner', 'api.workspace.delete'),
        ('owner', 'api.workspace.member.manage'),
        ('owner', 'api.kb.create'),
        ('owner', 'api.kb.read'),
        ('owner', 'api.kb.update'),
        ('owner', 'api.kb.delete'),
        ('owner', 'api.kb.member.manage'),
        ('owner', 'api.document.read'),
        ('owner', 'api.document.write'),
        ('owner', 'api.document.delete'),
        ('owner', 'api.retrieval.query'),
        ('owner', 'api.chat.completion'),
        ('owner', 'api.agent.run.create'),
        ('owner', 'api.agent.run.read'),
        ('owner', 'api.agent.run.cancel'),
        ('owner', 'menu.tenant'),
        ('owner', 'menu.workspace'),
        ('owner', 'menu.kb'),
        ('owner', 'menu.document'),
        ('owner', 'menu.user'),
        ('owner', 'button.tenant.update'),
        ('owner', 'button.tenant.delete'),
        ('owner', 'button.workspace.create'),
        ('owner', 'button.workspace.update'),
        ('owner', 'button.workspace.delete'),
        ('owner', 'button.kb.create'),
        ('owner', 'button.kb.update'),
        ('owner', 'button.kb.delete'),
        ('owner', 'button.document.upload'),
        ('owner', 'button.document.update'),
        ('owner', 'button.document.delete'),
        ('owner', 'button.member.add'),
        ('owner', 'button.member.remove'),
        ('owner', 'feature.auth.permissions'),

        -- admin: 不含 tenant.delete，其余同 owner
        ('admin', 'api.tenant.read'),
        ('admin', 'api.tenant.update'),
        ('admin', 'api.tenant.member.manage'),
        ('admin', 'api.user.read'),
        ('admin', 'api.user.update'),
        ('admin', 'api.workspace.create'),
        ('admin', 'api.workspace.read'),
        ('admin', 'api.workspace.update'),
        ('admin', 'api.workspace.delete'),
        ('admin', 'api.workspace.member.manage'),
        ('admin', 'api.kb.create'),
        ('admin', 'api.kb.read'),
        ('admin', 'api.kb.update'),
        ('admin', 'api.kb.delete'),
        ('admin', 'api.kb.member.manage'),
        ('admin', 'api.document.read'),
        ('admin', 'api.document.write'),
        ('admin', 'api.document.delete'),
        ('admin', 'api.retrieval.query'),
        ('admin', 'api.chat.completion'),
        ('admin', 'api.agent.run.create'),
        ('admin', 'api.agent.run.read'),
        ('admin', 'api.agent.run.cancel'),
        ('admin', 'menu.tenant'),
        ('admin', 'menu.workspace'),
        ('admin', 'menu.kb'),
        ('admin', 'menu.document'),
        ('admin', 'menu.user'),
        ('admin', 'button.tenant.update'),
        ('admin', 'button.tenant.delete'),
        ('admin', 'button.workspace.create'),
        ('admin', 'button.workspace.update'),
        ('admin', 'button.workspace.delete'),
        ('admin', 'button.kb.create'),
        ('admin', 'button.kb.update'),
        ('admin', 'button.kb.delete'),
        ('admin', 'button.document.upload'),
        ('admin', 'button.document.update'),
        ('admin', 'button.document.delete'),
        ('admin', 'button.member.add'),
        ('admin', 'button.member.remove'),
        ('admin', 'feature.auth.permissions'),

        -- member: 基础协作能力
        ('member', 'api.tenant.read'),
        ('member', 'api.workspace.create'),
        ('member', 'api.workspace.read'),
        ('member', 'api.kb.read'),
        ('member', 'api.document.read'),
        ('member', 'api.retrieval.query'),
        ('member', 'api.chat.completion'),
        ('member', 'api.agent.run.create'),
        ('member', 'api.agent.run.read'),
        ('member', 'api.agent.run.cancel'),
        ('member', 'menu.workspace'),
        ('member', 'menu.kb'),
        ('member', 'menu.document'),
        ('member', 'button.document.upload'),
        ('member', 'button.document.update'),
        ('member', 'button.document.delete'),

        -- viewer: 只读能力
        ('viewer', 'api.tenant.read'),
        ('viewer', 'api.workspace.read'),
        ('viewer', 'api.kb.read'),
        ('viewer', 'api.document.read'),
        ('viewer', 'api.retrieval.query'),
        ('viewer', 'api.chat.completion'),
        ('viewer', 'api.agent.run.create'),
        ('viewer', 'api.agent.run.read'),
        ('viewer', 'api.agent.run.cancel'),
        ('viewer', 'menu.workspace'),
        ('viewer', 'menu.kb'),
        ('viewer', 'menu.document')
),
candidate_roles AS (
    SELECT
        t.id AS tenant_id,
        r.role AS role
    FROM tenants AS t
    CROSS JOIN (VALUES ('owner'), ('admin'), ('member'), ('viewer')) AS r(role)
    WHERE NOT EXISTS (
        SELECT 1
        FROM tenant_role_permissions AS p
        WHERE p.tenant_id = t.id
          AND p.role = r.role
    )
)
INSERT INTO tenant_role_permissions (
    id,
    tenant_id,
    role,
    permission_code,
    created_at,
    updated_at
)
SELECT
    gen_random_uuid(),
    c.tenant_id,
    c.role,
    d.permission_code,
    NOW(),
    NOW()
FROM candidate_roles AS c
JOIN role_defaults AS d
  ON d.role = c.role
ON CONFLICT (tenant_id, role, permission_code) DO NOTHING;
