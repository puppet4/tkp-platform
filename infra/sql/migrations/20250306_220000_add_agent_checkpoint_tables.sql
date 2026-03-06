-- Agent 恢复点表迁移
-- 创建时间: 2025-03-06

-- Agent 恢复点表
CREATE TABLE IF NOT EXISTS agent_checkpoints (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    agent_run_id UUID NOT NULL,
    checkpoint_seq INTEGER DEFAULT 0 NOT NULL,
    checkpoint_type VARCHAR(50) NOT NULL,
    state_snapshot JSONB NOT NULL,
    completed_steps JSONB DEFAULT '[]'::jsonb,
    pending_steps JSONB DEFAULT '[]'::jsonb,
    context_data JSONB DEFAULT '{}'::jsonb,
    tool_call_history JSONB DEFAULT '[]'::jsonb,
    error_info JSONB,
    recoverable BOOLEAN DEFAULT TRUE NOT NULL,
    recovery_strategy VARCHAR(50),
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);

-- 索引
CREATE INDEX idx_agent_checkpoints_tenant_id ON agent_checkpoints(tenant_id);
CREATE INDEX idx_agent_checkpoints_agent_run_id ON agent_checkpoints(agent_run_id);
CREATE INDEX idx_agent_checkpoints_run_seq ON agent_checkpoints(agent_run_id, checkpoint_seq);

-- Agent 恢复记录表
CREATE TABLE IF NOT EXISTS agent_recoveries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    agent_run_id UUID NOT NULL,
    checkpoint_id UUID NOT NULL,
    status VARCHAR(50) DEFAULT 'pending' NOT NULL,
    recovery_strategy VARCHAR(50) NOT NULL,
    before_state JSONB,
    after_state JSONB,
    recovery_result JSONB,
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    completed_at TIMESTAMP WITH TIME ZONE
);

-- 索引
CREATE INDEX idx_agent_recoveries_tenant_id ON agent_recoveries(tenant_id);
CREATE INDEX idx_agent_recoveries_agent_run_id ON agent_recoveries(agent_run_id);
CREATE INDEX idx_agent_recoveries_checkpoint_id ON agent_recoveries(checkpoint_id);
CREATE INDEX idx_agent_recoveries_status ON agent_recoveries(status);

-- 外键约束
ALTER TABLE agent_checkpoints
    ADD CONSTRAINT fk_agent_checkpoints_tenant
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE;

ALTER TABLE agent_checkpoints
    ADD CONSTRAINT fk_agent_checkpoints_agent_run
    FOREIGN KEY (agent_run_id) REFERENCES agent_runs(id) ON DELETE CASCADE;

ALTER TABLE agent_recoveries
    ADD CONSTRAINT fk_agent_recoveries_tenant
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE;

ALTER TABLE agent_recoveries
    ADD CONSTRAINT fk_agent_recoveries_agent_run
    FOREIGN KEY (agent_run_id) REFERENCES agent_runs(id) ON DELETE CASCADE;

ALTER TABLE agent_recoveries
    ADD CONSTRAINT fk_agent_recoveries_checkpoint
    FOREIGN KEY (checkpoint_id) REFERENCES agent_checkpoints(id) ON DELETE CASCADE;

-- 注释
COMMENT ON TABLE agent_checkpoints IS 'Agent 执行恢复点表';
COMMENT ON TABLE agent_recoveries IS 'Agent 恢复记录表';
