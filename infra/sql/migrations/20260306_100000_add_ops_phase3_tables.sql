BEGIN;

CREATE TABLE IF NOT EXISTS ops_incident_tickets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    source_code VARCHAR(64) NOT NULL,
    severity VARCHAR(16) NOT NULL DEFAULT 'warn',
    status VARCHAR(16) NOT NULL DEFAULT 'open',
    title VARCHAR(256) NOT NULL,
    summary TEXT NOT NULL,
    diagnosis_json JSONB NOT NULL DEFAULT '{}'::JSONB,
    context_json JSONB NOT NULL DEFAULT '{}'::JSONB,
    assignee_user_id UUID NULL,
    resolution_note TEXT NULL,
    created_by UUID NULL,
    resolved_at VARCHAR(64) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_ops_incident_tickets_severity CHECK (severity IN ('info', 'warn', 'critical')),
    CONSTRAINT ck_ops_incident_tickets_status CHECK (status IN ('open', 'acknowledged', 'resolved'))
);

CREATE INDEX IF NOT EXISTS ix_ops_incident_tickets_tenant_status_created_at
    ON ops_incident_tickets (tenant_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_ops_incident_tickets_source_code
    ON ops_incident_tickets (source_code);

CREATE TABLE IF NOT EXISTS ops_alert_webhooks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    name VARCHAR(64) NOT NULL,
    url TEXT NOT NULL,
    secret VARCHAR(256) NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    event_types JSONB NOT NULL DEFAULT '[]'::JSONB,
    timeout_seconds INTEGER NOT NULL DEFAULT 3,
    last_status_code INTEGER NULL,
    last_error TEXT NULL,
    last_notified_at VARCHAR(64) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uk_ops_alert_webhook_name UNIQUE (tenant_id, name),
    CONSTRAINT ck_ops_alert_webhooks_timeout_seconds CHECK (timeout_seconds >= 1 AND timeout_seconds <= 30)
);

CREATE INDEX IF NOT EXISTS ix_ops_alert_webhooks_tenant_enabled
    ON ops_alert_webhooks (tenant_id, enabled);

COMMENT ON TABLE ops_incident_tickets IS '运维异常工单表。';
COMMENT ON COLUMN ops_incident_tickets.tenant_id IS '租户 ID。';
COMMENT ON COLUMN ops_incident_tickets.source_code IS '异常来源编码。';
COMMENT ON COLUMN ops_incident_tickets.severity IS '工单严重级别。';
COMMENT ON COLUMN ops_incident_tickets.status IS '工单状态。';
COMMENT ON COLUMN ops_incident_tickets.title IS '工单标题。';
COMMENT ON COLUMN ops_incident_tickets.summary IS '异常摘要。';
COMMENT ON COLUMN ops_incident_tickets.diagnosis_json IS '诊断详情 JSON。';
COMMENT ON COLUMN ops_incident_tickets.context_json IS '上下文 JSON。';
COMMENT ON COLUMN ops_incident_tickets.assignee_user_id IS '当前处理人用户 ID。';
COMMENT ON COLUMN ops_incident_tickets.resolution_note IS '处理结论。';
COMMENT ON COLUMN ops_incident_tickets.created_by IS '工单创建人用户 ID。';
COMMENT ON COLUMN ops_incident_tickets.resolved_at IS '工单关闭时间（ISO8601）。';
COMMENT ON COLUMN ops_incident_tickets.created_at IS '创建时间。';
COMMENT ON COLUMN ops_incident_tickets.updated_at IS '更新时间。';

COMMENT ON TABLE ops_alert_webhooks IS '告警 webhook 订阅表。';
COMMENT ON COLUMN ops_alert_webhooks.tenant_id IS '租户 ID。';
COMMENT ON COLUMN ops_alert_webhooks.name IS '订阅名称。';
COMMENT ON COLUMN ops_alert_webhooks.url IS 'webhook 地址。';
COMMENT ON COLUMN ops_alert_webhooks.secret IS '可选签名密钥。';
COMMENT ON COLUMN ops_alert_webhooks.enabled IS '是否启用。';
COMMENT ON COLUMN ops_alert_webhooks.event_types IS '订阅事件类型列表。';
COMMENT ON COLUMN ops_alert_webhooks.timeout_seconds IS '通知超时时间（秒）。';
COMMENT ON COLUMN ops_alert_webhooks.last_status_code IS '最近一次通知响应码。';
COMMENT ON COLUMN ops_alert_webhooks.last_error IS '最近一次通知错误。';
COMMENT ON COLUMN ops_alert_webhooks.last_notified_at IS '最近一次通知时间（ISO8601）。';
COMMENT ON COLUMN ops_alert_webhooks.created_at IS '创建时间。';
COMMENT ON COLUMN ops_alert_webhooks.updated_at IS '更新时间。';

COMMIT;
