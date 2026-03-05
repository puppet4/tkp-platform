BEGIN;

CREATE TABLE IF NOT EXISTS ops_release_rollouts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    version VARCHAR(64) NOT NULL,
    strategy VARCHAR(32) NOT NULL DEFAULT 'canary',
    status VARCHAR(32) NOT NULL DEFAULT 'planned',
    risk_level VARCHAR(16) NOT NULL DEFAULT 'medium',
    canary_percent INTEGER NOT NULL DEFAULT 10,
    scope_json JSONB NOT NULL DEFAULT '{}'::JSONB,
    rollback_of UUID NULL,
    approved_by UUID NULL,
    note TEXT NULL,
    started_at VARCHAR(64) NULL,
    completed_at VARCHAR(64) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_ops_release_rollouts_strategy CHECK (strategy IN ('canary', 'blue_green', 'rolling')),
    CONSTRAINT ck_ops_release_rollouts_status CHECK (status IN ('planned', 'running', 'completed', 'rolled_back', 'canceled')),
    CONSTRAINT ck_ops_release_rollouts_risk_level CHECK (risk_level IN ('low', 'medium', 'high')),
    CONSTRAINT ck_ops_release_rollouts_canary_percent CHECK (canary_percent >= 0 AND canary_percent <= 100)
);

CREATE INDEX IF NOT EXISTS ix_ops_release_rollouts_tenant_created_at
    ON ops_release_rollouts (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_ops_release_rollouts_tenant_status
    ON ops_release_rollouts (tenant_id, status);
CREATE INDEX IF NOT EXISTS ix_ops_release_rollouts_version
    ON ops_release_rollouts (version);
CREATE INDEX IF NOT EXISTS ix_ops_release_rollouts_rollback_of
    ON ops_release_rollouts (rollback_of);

CREATE TABLE IF NOT EXISTS ops_deletion_proofs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    resource_type VARCHAR(64) NOT NULL,
    resource_id VARCHAR(128) NOT NULL,
    subject_hash VARCHAR(128) NOT NULL,
    signature VARCHAR(128) NOT NULL,
    deleted_by UUID NULL,
    deleted_at VARCHAR(64) NOT NULL,
    ticket_id UUID NULL,
    proof_payload JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_ops_deletion_proofs_resource_type CHECK (resource_type IN ('document', 'knowledge_base', 'workspace', 'tenant', 'user'))
);

CREATE INDEX IF NOT EXISTS ix_ops_deletion_proofs_tenant_created_at
    ON ops_deletion_proofs (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_ops_deletion_proofs_resource
    ON ops_deletion_proofs (tenant_id, resource_type, resource_id);
CREATE INDEX IF NOT EXISTS ix_ops_deletion_proofs_subject_hash
    ON ops_deletion_proofs (subject_hash);
CREATE INDEX IF NOT EXISTS ix_ops_deletion_proofs_ticket_id
    ON ops_deletion_proofs (ticket_id);

COMMENT ON TABLE ops_release_rollouts IS '发布与回滚记录表。';
COMMENT ON COLUMN ops_release_rollouts.tenant_id IS '租户 ID。';
COMMENT ON COLUMN ops_release_rollouts.version IS '发布版本标识。';
COMMENT ON COLUMN ops_release_rollouts.strategy IS '发布策略（canary/blue_green/rolling）。';
COMMENT ON COLUMN ops_release_rollouts.status IS '发布状态。';
COMMENT ON COLUMN ops_release_rollouts.risk_level IS '变更风险等级。';
COMMENT ON COLUMN ops_release_rollouts.canary_percent IS '金丝雀灰度比例（0-100）。';
COMMENT ON COLUMN ops_release_rollouts.scope_json IS '发布范围定义。';
COMMENT ON COLUMN ops_release_rollouts.rollback_of IS '若为回滚动作，指向被回滚发布 ID。';
COMMENT ON COLUMN ops_release_rollouts.approved_by IS '审批人用户 ID。';
COMMENT ON COLUMN ops_release_rollouts.note IS '发布备注。';
COMMENT ON COLUMN ops_release_rollouts.started_at IS '发布启动时间（ISO8601）。';
COMMENT ON COLUMN ops_release_rollouts.completed_at IS '发布完成时间（ISO8601）。';
COMMENT ON COLUMN ops_release_rollouts.created_at IS '创建时间。';
COMMENT ON COLUMN ops_release_rollouts.updated_at IS '更新时间。';

COMMENT ON TABLE ops_deletion_proofs IS '删除证明记录表。';
COMMENT ON COLUMN ops_deletion_proofs.tenant_id IS '租户 ID。';
COMMENT ON COLUMN ops_deletion_proofs.resource_type IS '删除资源类型。';
COMMENT ON COLUMN ops_deletion_proofs.resource_id IS '删除资源标识。';
COMMENT ON COLUMN ops_deletion_proofs.subject_hash IS '删除主体摘要（hash）。';
COMMENT ON COLUMN ops_deletion_proofs.signature IS '证明签名。';
COMMENT ON COLUMN ops_deletion_proofs.deleted_by IS '执行删除的用户 ID。';
COMMENT ON COLUMN ops_deletion_proofs.deleted_at IS '删除发生时间（ISO8601）。';
COMMENT ON COLUMN ops_deletion_proofs.ticket_id IS '关联排障/工单 ID。';
COMMENT ON COLUMN ops_deletion_proofs.proof_payload IS '删除证明补充载荷。';
COMMENT ON COLUMN ops_deletion_proofs.created_at IS '创建时间。';
COMMENT ON COLUMN ops_deletion_proofs.updated_at IS '更新时间。';

COMMIT;
