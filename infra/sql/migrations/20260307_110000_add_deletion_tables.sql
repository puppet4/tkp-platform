-- 数据删除请求表
CREATE TABLE IF NOT EXISTS deletion_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL,
    resource_type VARCHAR(50) NOT NULL,
    resource_id UUID NOT NULL,
    reason TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    requested_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    approved_by UUID,
    approved_at TIMESTAMP,
    rejected_by UUID,
    rejected_at TIMESTAMP,
    reject_reason TEXT,
    executed_by UUID,
    executed_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 索引
CREATE INDEX idx_deletion_requests_tenant_id ON deletion_requests(tenant_id);
CREATE INDEX idx_deletion_requests_status ON deletion_requests(status);
CREATE INDEX idx_deletion_requests_resource ON deletion_requests(resource_type, resource_id);

-- 注释
COMMENT ON TABLE deletion_requests IS '数据删除请求表';
COMMENT ON COLUMN deletion_requests.id IS '请求 ID';
COMMENT ON COLUMN deletion_requests.tenant_id IS '租户 ID';
COMMENT ON COLUMN deletion_requests.user_id IS '请求用户 ID';
COMMENT ON COLUMN deletion_requests.resource_type IS '资源类型（document/user/conversation）';
COMMENT ON COLUMN deletion_requests.resource_id IS '资源 ID';
COMMENT ON COLUMN deletion_requests.reason IS '删除原因';
COMMENT ON COLUMN deletion_requests.status IS '状态（pending/approved/rejected/completed）';

-- 数据删除证明表
CREATE TABLE IF NOT EXISTS deletion_proofs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id UUID NOT NULL REFERENCES deletion_requests(id),
    tenant_id UUID NOT NULL,
    resource_type VARCHAR(50) NOT NULL,
    resource_id UUID NOT NULL,
    deleted_at TIMESTAMP NOT NULL,
    deleted_by UUID NOT NULL,
    data_hash VARCHAR(64) NOT NULL,
    proof_hash VARCHAR(64) NOT NULL,
    metadata JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 索引
CREATE INDEX idx_deletion_proofs_tenant_id ON deletion_proofs(tenant_id);
CREATE INDEX idx_deletion_proofs_request_id ON deletion_proofs(request_id);
CREATE INDEX idx_deletion_proofs_resource ON deletion_proofs(resource_type, resource_id);
CREATE INDEX idx_deletion_proofs_proof_hash ON deletion_proofs(proof_hash);

-- 注释
COMMENT ON TABLE deletion_proofs IS '数据删除证明表';
COMMENT ON COLUMN deletion_proofs.id IS '证明 ID';
COMMENT ON COLUMN deletion_proofs.request_id IS '删除请求 ID';
COMMENT ON COLUMN deletion_proofs.tenant_id IS '租户 ID';
COMMENT ON COLUMN deletion_proofs.resource_type IS '资源类型';
COMMENT ON COLUMN deletion_proofs.resource_id IS '资源 ID';
COMMENT ON COLUMN deletion_proofs.deleted_at IS '删除时间';
COMMENT ON COLUMN deletion_proofs.deleted_by IS '执行删除的用户 ID';
COMMENT ON COLUMN deletion_proofs.data_hash IS '删除数据的哈希值';
COMMENT ON COLUMN deletion_proofs.proof_hash IS '证明的哈希值（用于验证完整性）';
COMMENT ON COLUMN deletion_proofs.metadata IS '额外元数据';
