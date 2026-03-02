BEGIN;

INSERT INTO tenant_role_permissions (id, tenant_id, role, permission_code, created_at, updated_at)
SELECT gen_random_uuid(), rp.tenant_id, 'owner', 'api.user.delete', NOW(), NOW()
FROM (
    SELECT DISTINCT tenant_id
    FROM tenant_role_permissions
    WHERE role = 'owner'
) AS rp
ON CONFLICT (tenant_id, role, permission_code) DO NOTHING;

INSERT INTO tenant_role_permissions (id, tenant_id, role, permission_code, created_at, updated_at)
SELECT gen_random_uuid(), rp.tenant_id, 'owner', 'button.user.delete', NOW(), NOW()
FROM (
    SELECT DISTINCT tenant_id
    FROM tenant_role_permissions
    WHERE role = 'owner'
) AS rp
ON CONFLICT (tenant_id, role, permission_code) DO NOTHING;

INSERT INTO tenant_role_permissions (id, tenant_id, role, permission_code, created_at, updated_at)
SELECT gen_random_uuid(), rp.tenant_id, 'admin', 'api.user.delete', NOW(), NOW()
FROM (
    SELECT DISTINCT tenant_id
    FROM tenant_role_permissions
    WHERE role = 'admin'
) AS rp
ON CONFLICT (tenant_id, role, permission_code) DO NOTHING;

INSERT INTO tenant_role_permissions (id, tenant_id, role, permission_code, created_at, updated_at)
SELECT gen_random_uuid(), rp.tenant_id, 'admin', 'button.user.delete', NOW(), NOW()
FROM (
    SELECT DISTINCT tenant_id
    FROM tenant_role_permissions
    WHERE role = 'admin'
) AS rp
ON CONFLICT (tenant_id, role, permission_code) DO NOTHING;

COMMIT;
