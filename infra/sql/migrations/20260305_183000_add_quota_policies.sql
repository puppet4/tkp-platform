BEGIN;

CREATE TABLE IF NOT EXISTS quota_policies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    scope_type VARCHAR(16) NOT NULL,
    scope_id UUID NOT NULL,
    metric_code VARCHAR(64) NOT NULL,
    limit_value INTEGER NOT NULL,
    window_minutes INTEGER NOT NULL DEFAULT 1440,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_by UUID NULL,
    updated_by UUID NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uk_quota_policy_scope_metric UNIQUE (tenant_id, scope_type, scope_id, metric_code),
    CONSTRAINT ck_quota_policies_scope_type CHECK (scope_type IN ('tenant', 'workspace')),
    CONSTRAINT ck_quota_policies_limit_value CHECK (limit_value >= 0),
    CONSTRAINT ck_quota_policies_window_minutes CHECK (window_minutes >= 1)
);

CREATE INDEX IF NOT EXISTS ix_quota_policies_tenant_scope
    ON quota_policies (tenant_id, scope_type, scope_id);
CREATE INDEX IF NOT EXISTS ix_quota_policies_metric_enabled
    ON quota_policies (metric_code, enabled);

COMMENT ON TABLE quota_policies IS '租户与工作空间配额策略表。';
COMMENT ON COLUMN quota_policies.tenant_id IS '租户 ID。';
COMMENT ON COLUMN quota_policies.scope_type IS '配额范围类型（tenant/workspace）。';
COMMENT ON COLUMN quota_policies.scope_id IS '配额范围 ID。tenant 级为 tenant_id，workspace 级为 workspace_id。';
COMMENT ON COLUMN quota_policies.metric_code IS '配额指标编码。';
COMMENT ON COLUMN quota_policies.limit_value IS '窗口内允许上限值。';
COMMENT ON COLUMN quota_policies.window_minutes IS '统计窗口分钟数。';
COMMENT ON COLUMN quota_policies.enabled IS '是否启用该策略。';
COMMENT ON COLUMN quota_policies.created_by IS '创建策略用户 ID。';
COMMENT ON COLUMN quota_policies.updated_by IS '最后更新策略用户 ID。';
COMMENT ON COLUMN quota_policies.created_at IS '创建时间。';
COMMENT ON COLUMN quota_policies.updated_at IS '更新时间。';

COMMIT;
