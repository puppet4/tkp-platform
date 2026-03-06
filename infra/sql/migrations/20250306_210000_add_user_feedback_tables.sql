-- 用户反馈和回放表迁移
-- 创建时间: 2025-03-06

-- 用户反馈表
CREATE TABLE IF NOT EXISTS user_feedbacks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL,
    conversation_id UUID,
    message_id UUID,
    retrieval_log_id UUID,
    feedback_type VARCHAR(50) NOT NULL,
    feedback_value VARCHAR(255),
    comment TEXT,
    tags JSONB,
    snapshot JSONB,
    processed BOOLEAN DEFAULT FALSE NOT NULL,
    processed_at TIMESTAMP WITH TIME ZONE,
    processing_result JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);

-- 索引
CREATE INDEX idx_user_feedbacks_tenant_id ON user_feedbacks(tenant_id);
CREATE INDEX idx_user_feedbacks_user_id ON user_feedbacks(user_id);
CREATE INDEX idx_user_feedbacks_conversation_id ON user_feedbacks(conversation_id);
CREATE INDEX idx_user_feedbacks_message_id ON user_feedbacks(message_id);
CREATE INDEX idx_user_feedbacks_retrieval_log_id ON user_feedbacks(retrieval_log_id);
CREATE INDEX idx_user_feedbacks_feedback_type ON user_feedbacks(feedback_type);
CREATE INDEX idx_user_feedbacks_processed ON user_feedbacks(processed);

-- 反馈回放表
CREATE TABLE IF NOT EXISTS feedback_replays (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    feedback_id UUID NOT NULL,
    replay_type VARCHAR(50) NOT NULL,
    status VARCHAR(50) DEFAULT 'pending' NOT NULL,
    original_result JSONB,
    replay_result JSONB,
    comparison JSONB,
    suggestions JSONB,
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    completed_at TIMESTAMP WITH TIME ZONE
);

-- 索引
CREATE INDEX idx_feedback_replays_tenant_id ON feedback_replays(tenant_id);
CREATE INDEX idx_feedback_replays_feedback_id ON feedback_replays(feedback_id);
CREATE INDEX idx_feedback_replays_status ON feedback_replays(status);

-- 外键约束
ALTER TABLE user_feedbacks
    ADD CONSTRAINT fk_user_feedbacks_tenant
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE;

ALTER TABLE user_feedbacks
    ADD CONSTRAINT fk_user_feedbacks_user
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;

ALTER TABLE feedback_replays
    ADD CONSTRAINT fk_feedback_replays_tenant
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE;

ALTER TABLE feedback_replays
    ADD CONSTRAINT fk_feedback_replays_feedback
    FOREIGN KEY (feedback_id) REFERENCES user_feedbacks(id) ON DELETE CASCADE;

-- 注释
COMMENT ON TABLE user_feedbacks IS '用户反馈表';
COMMENT ON TABLE feedback_replays IS '反馈回放记录表';
