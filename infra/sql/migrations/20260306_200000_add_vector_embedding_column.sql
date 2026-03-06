BEGIN;

-- 为 document_chunks 添加向量列以支持语义检索
-- 使用 1536 维度（OpenAI text-embedding-3-small 默认维度）

ALTER TABLE document_chunks
ADD COLUMN IF NOT EXISTS embedding vector(1536);

-- 为向量列创建 HNSW 索引以加速相似度搜索
-- 使用余弦距离（cosine distance）作为相似度度量
CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding_cosine
ON document_chunks
USING hnsw (embedding vector_cosine_ops);

-- 添加嵌入模型标识列，用于追踪使用的模型版本
ALTER TABLE document_chunks
ADD COLUMN IF NOT EXISTS embedding_model VARCHAR(128);

-- 添加嵌入生成时间戳
ALTER TABLE document_chunks
ADD COLUMN IF NOT EXISTS embedded_at TIMESTAMPTZ;

COMMENT ON COLUMN document_chunks.embedding IS '文本块的向量表示，用于语义检索';
COMMENT ON COLUMN document_chunks.embedding_model IS '生成向量的模型标识（如 text-embedding-3-small）';
COMMENT ON COLUMN document_chunks.embedded_at IS '向量生成时间';

COMMIT;