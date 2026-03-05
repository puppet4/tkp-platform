BEGIN;

CREATE TABLE IF NOT EXISTS retrieval_eval_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    created_by UUID NOT NULL,
    name VARCHAR(128) NOT NULL DEFAULT 'adhoc',
    kb_ids JSONB NOT NULL DEFAULT '[]'::JSONB,
    top_k INTEGER NOT NULL DEFAULT 5,
    sample_total INTEGER NOT NULL DEFAULT 0,
    matched_total INTEGER NOT NULL DEFAULT 0,
    hit_at_k DOUBLE PRECISION NOT NULL DEFAULT 0,
    citation_coverage_rate DOUBLE PRECISION NOT NULL DEFAULT 0,
    avg_latency_ms INTEGER NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'completed',
    summary_json JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_retrieval_eval_runs_top_k CHECK (top_k > 0),
    CONSTRAINT ck_retrieval_eval_runs_sample_total CHECK (sample_total >= 0),
    CONSTRAINT ck_retrieval_eval_runs_matched_total CHECK (matched_total >= 0),
    CONSTRAINT ck_retrieval_eval_runs_hit_at_k CHECK (hit_at_k >= 0 AND hit_at_k <= 1),
    CONSTRAINT ck_retrieval_eval_runs_citation_coverage_rate CHECK (
        citation_coverage_rate >= 0 AND citation_coverage_rate <= 1
    ),
    CONSTRAINT ck_retrieval_eval_runs_status CHECK (status IN ('queued', 'running', 'completed', 'failed'))
);

CREATE TABLE IF NOT EXISTS retrieval_eval_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    sample_no INTEGER NOT NULL,
    query_text TEXT NOT NULL,
    expected_terms JSONB NOT NULL DEFAULT '[]'::JSONB,
    matched BOOLEAN NOT NULL DEFAULT FALSE,
    hit_count INTEGER NOT NULL DEFAULT 0,
    citation_covered BOOLEAN NOT NULL DEFAULT FALSE,
    top_hit_score INTEGER NULL,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    result_json JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uk_retrieval_eval_item_run_no UNIQUE (run_id, sample_no),
    CONSTRAINT ck_retrieval_eval_items_sample_no CHECK (sample_no > 0),
    CONSTRAINT ck_retrieval_eval_items_hit_count CHECK (hit_count >= 0),
    CONSTRAINT ck_retrieval_eval_items_latency_ms CHECK (latency_ms >= 0)
);

CREATE INDEX IF NOT EXISTS ix_retrieval_eval_runs_tenant_created_at
    ON retrieval_eval_runs (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_retrieval_eval_runs_created_by
    ON retrieval_eval_runs (created_by);
CREATE INDEX IF NOT EXISTS ix_retrieval_eval_items_tenant_run
    ON retrieval_eval_items (tenant_id, run_id);
CREATE INDEX IF NOT EXISTS ix_retrieval_eval_items_run_sample_no
    ON retrieval_eval_items (run_id, sample_no);

COMMENT ON TABLE retrieval_eval_runs IS '检索评测运行记录表。';
COMMENT ON COLUMN retrieval_eval_runs.tenant_id IS '租户 ID。';
COMMENT ON COLUMN retrieval_eval_runs.created_by IS '发起评测用户 ID。';
COMMENT ON COLUMN retrieval_eval_runs.name IS '评测任务名称。';
COMMENT ON COLUMN retrieval_eval_runs.kb_ids IS '评测范围知识库 ID 列表。';
COMMENT ON COLUMN retrieval_eval_runs.top_k IS '评测检索 top_k。';
COMMENT ON COLUMN retrieval_eval_runs.sample_total IS '样本总数。';
COMMENT ON COLUMN retrieval_eval_runs.matched_total IS '命中样本数。';
COMMENT ON COLUMN retrieval_eval_runs.hit_at_k IS '命中率。';
COMMENT ON COLUMN retrieval_eval_runs.citation_coverage_rate IS '引用覆盖率。';
COMMENT ON COLUMN retrieval_eval_runs.avg_latency_ms IS '平均延迟。';
COMMENT ON COLUMN retrieval_eval_runs.status IS '运行状态。';
COMMENT ON COLUMN retrieval_eval_runs.summary_json IS '汇总快照。';
COMMENT ON COLUMN retrieval_eval_runs.created_at IS '创建时间。';
COMMENT ON COLUMN retrieval_eval_runs.updated_at IS '更新时间。';

COMMENT ON TABLE retrieval_eval_items IS '检索评测样本明细表。';
COMMENT ON COLUMN retrieval_eval_items.run_id IS '评测运行 ID。';
COMMENT ON COLUMN retrieval_eval_items.tenant_id IS '租户 ID。';
COMMENT ON COLUMN retrieval_eval_items.sample_no IS '样本序号。';
COMMENT ON COLUMN retrieval_eval_items.query_text IS '评测问题。';
COMMENT ON COLUMN retrieval_eval_items.expected_terms IS '预期关键词列表。';
COMMENT ON COLUMN retrieval_eval_items.matched IS '是否命中。';
COMMENT ON COLUMN retrieval_eval_items.hit_count IS '命中数。';
COMMENT ON COLUMN retrieval_eval_items.citation_covered IS '引用覆盖情况。';
COMMENT ON COLUMN retrieval_eval_items.top_hit_score IS '第一命中分。';
COMMENT ON COLUMN retrieval_eval_items.latency_ms IS '检索延迟毫秒。';
COMMENT ON COLUMN retrieval_eval_items.result_json IS '样本结果快照。';
COMMENT ON COLUMN retrieval_eval_items.created_at IS '创建时间。';

COMMIT;
