# TKP Platform Monorepo

Multi-service repository for a multi-tenant knowledge platform.

## 🎉 核心功能已实现

✅ **完整的 RAG 功能**
- PDF/Word/PowerPoint 文档解析
- 智能文本切片（保持段落完整性）
- OpenAI Embeddings 向量化
- pgvector 语义检索
- **混合检索（向量 + 全文 + BM25）** 🆕
- **智能重排序（Cohere/Jina/Cross-Encoder）** 🆕
- **查询改写（Query Expansion）** 🆕
- OpenAI GPT 智能问答
- 自动引用来源

✅ **生产级架构**
- 多租户隔离
- 异步文档处理
- 向量索引优化（HNSW）
- Elasticsearch 全文索引 🆕
- 错误处理和回退机制

## 📚 文档

- **实施指南**: `docs/IMPLEMENTATION_GUIDE.md` - 完整的部署和使用说明
- **实施总结**: `docs/IMPLEMENTATION_SUMMARY.md` - 功能清单和技术架构
- **代码导读**: `docs/code-guide.md` - 代码结构说明
- **架构设计**: `docs/knowledge-platform-architecture.md` - 系统架构文档

## 🚀 快速开始

### 1. 配置环境

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑 .env 文件，配置以下必填项：
# - KD_OPENAI_API_KEY=sk-your-key-here
# - KD_AUTH_JWT_SECRET=your-secret-at-least-32-bytes
```

### 2. 安装依赖

```bash
uv sync
```

### 3. 启动基础设施（使用 Docker Compose）

```bash
# 启动 PostgreSQL、Redis、Elasticsearch、MinIO
docker-compose up -d

# 等待服务就绪
docker-compose ps
```

### 4. 初始化数据库

```bash
# 使用统一的初始化脚本
psql "$KD_DATABASE_URL" -f sql/init_all.sql
```

### 5. 同步 Elasticsearch 索引（可选）

```bash
# 如果启用了 Elasticsearch，需要同步现有数据
PYTHONPATH=services/api/src uv run --project services/api python services/api/scripts/sync_elasticsearch.py
```

### 6. 启动服务

手动启动：

```bash
# 终端 1: 启动 API 服务（包含 RAG 功能）
PYTHONPATH=services/api/src uv run --project services/api uvicorn tkp_api.main:app --reload --port 8000

# 终端 2: 启动 Worker 服务
PYTHONPATH=services/worker/src uv run --project services/worker python -m tkp_worker.main
```

### 7. 访问服务

- API 文档: http://localhost:8000/docs
- API 服务: http://localhost:8000
- Elasticsearch: http://localhost:9200
- MinIO Console: http://localhost:9001

## 🔧 高级功能配置

### 启用混合检索

在 `.env` 文件中配置：

```bash
# 启用 Elasticsearch
KD_ELASTICSEARCH_ENABLED=true
KD_ELASTICSEARCH_HOSTS=http://localhost:9200

# 设置检索策略
KD_RETRIEVAL_DEFAULT_STRATEGY=hybrid  # vector/fulltext/hybrid
KD_RETRIEVAL_VECTOR_WEIGHT=0.5
KD_RETRIEVAL_FULLTEXT_WEIGHT=0.5
```

### 启用重排序

```bash
# 启用重排序
KD_RETRIEVAL_ENABLE_RERANK=true

# 配置重排序提供商（cohere/jina/cross-encoder）
KD_RERANK_PROVIDER=cohere
KD_RERANK_API_KEY=your-cohere-api-key
KD_RERANK_TOP_N=5
```

### 启用查询改写

```bash
# 启用查询改写
KD_RETRIEVAL_ENABLE_QUERY_REWRITE=true

# 配置改写策略（expansion/multi_query/synonym）
KD_QUERY_REWRITE_STRATEGY=expansion
```

## 📊 可观测性

### 启用分布式追踪和指标

```bash
# 启用可观测性
KD_OBSERVABILITY_ENABLED=true
KD_OBSERVABILITY_OTLP_ENDPOINT=http://localhost:4317

# 配置日志格式
KD_OBSERVABILITY_LOG_FORMAT=json
KD_OBSERVABILITY_LOG_LEVEL=INFO
```

### 访问监控面板

启动 docker-compose 后，可以访问：

- **Jaeger UI** (分布式追踪): http://localhost:16686
- **Prometheus** (指标存储): http://localhost:9090
- **Grafana** (监控面板): http://localhost:3000
  - 默认用户名/密码: admin/admin
  - 预配置的 TKP Platform Overview 仪表板

### 指标端点

- **Prometheus 指标**: http://localhost:8000/metrics
- **健康检查**: http://localhost:8000/health/live
- **就绪检查**: http://localhost:8000/health/ready
- **详细健康检查**: http://localhost:8000/health/detailed

## 🔒 数据治理与合规

### 启用 Row Level Security (RLS)

```bash
# 初始化数据库（包含 RLS 相关结构）
psql "$KD_DATABASE_URL" -f sql/init_all.sql

# 在应用配置中启用
KD_GOVERNANCE_ENABLE_RLS=true
```

### PII 检测和脱敏

```bash
# 启用 PII 检测和脱敏
KD_GOVERNANCE_ENABLE_PII_DETECTION=true
KD_GOVERNANCE_ENABLE_PII_MASKING=true
```

系统会自动检测和脱敏以下类型的敏感信息：
- 邮箱地址
- 手机号码
- 身份证号
- 银行卡号
- IP 地址

### 数据删除证明流程

```bash
# 初始化数据库（包含删除请求与证明表）
psql "$KD_DATABASE_URL" -f sql/init_all.sql

# 配置删除审批
KD_GOVERNANCE_DELETION_REQUIRE_APPROVAL=true
```

数据删除流程：
1. 用户提交删除请求
2. 管理员审批/拒绝
3. 执行删除并生成证明
4. 证明永久保留用于合规审计

### 数据保留策略

```bash
# 启用数据保留策略
KD_GOVERNANCE_RETENTION_ENABLED=true
```

默认保留策略：
- 审计日志：365天
- 检索日志：90天
- 对话记录：180天
- Agent 运行记录：90天
- 删除证明：永久保留

## 🤖 Agent 高级功能

### 启用 Agent 沙箱

```bash
# 启用沙箱执行环境
KD_AGENT_ENABLE_SANDBOX=true
KD_AGENT_SANDBOX_TIMEOUT=30
KD_AGENT_SANDBOX_MAX_MEMORY_MB=512
```

Agent 沙箱提供：
- 隔离的代码执行环境
- 资源限制（CPU、内存、超时）
- 禁止危险操作（文件系统、网络）
- Docker 容器隔离（如果可用）

### 启用 Agent Guardrail

```bash
# 启用 Guardrail 防护
KD_AGENT_ENABLE_GUARDRAIL=true
KD_AGENT_RATE_LIMIT_PER_MINUTE=60
```

Guardrail 功能：
- 输入内容安全检查
- 输出敏感信息过滤
- 工具调用白名单验证
- 速率限制保护

### 多工具编排

系统内置多种工具：
- **retrieval**: 知识库检索
- **calculator**: 数学计算
- **web_search**: 网络搜索（占位）
- **datetime**: 日期时间操作

配置允许的工具：
```bash
KD_AGENT_ALLOWED_TOOLS=retrieval,calculator,datetime
```

## 🗄️ 存储架构

### 数据存储层

系统使用多种存储技术，各司其职：

- **PostgreSQL + pgvector**: 结构化数据和向量存储
- **Elasticsearch**: 全文检索索引
- **Redis**: 缓存和会话存储
- **MinIO/OSS**: 对象存储（文档文件）
- **Kafka**: 事件流和消息队列

### 启用 Kafka 事件总线

```bash
# 启用 Kafka
KD_KAFKA_ENABLED=true
KD_KAFKA_BOOTSTRAP_SERVERS=localhost:9092
```

Kafka 主题：
- **document-events**: 文档上传、处理、删除事件
- **retrieval-events**: 检索查询事件
- **chat-events**: 聊天消息事件
- **agent-events**: Agent 运行事件
- **user-events**: 用户相关事件

### 事件驱动架构

系统通过事件总线实现松耦合：
1. API 服务发布事件到 Kafka
2. Worker 服务订阅事件并处理
3. 支持异步处理和重试机制
4. 便于扩展和监控

## 📄 文档解析增强

### 启用 OCR 文字识别

```bash
# 安装 Tesseract OCR（系统依赖）
# macOS: brew install tesseract tesseract-lang
# Ubuntu: apt-get install tesseract-ocr tesseract-ocr-chi-sim

# 启用 OCR
KD_OCR_ENABLED=true
KD_OCR_ENGINE=tesseract
KD_OCR_LANGUAGE=eng+chi_sim
```

支持的 OCR 引擎：
- **Tesseract**: 开源 OCR 引擎，支持多语言
- **PaddleOCR**: 百度开源的中文 OCR 引擎（需额外安装）

### 图片解析功能

```bash
# 启用图片描述生成（使用 GPT-4 Vision）
KD_IMAGE_DESCRIPTION_ENABLED=true

# 启用缩略图生成
KD_IMAGE_THUMBNAIL_ENABLED=true
KD_IMAGE_THUMBNAIL_MAX_SIZE=300
```

图片解析功能：
- 提取图片元数据（尺寸、格式、EXIF）
- 生成缩略图
- OCR 文字识别
- AI 图片描述生成

### 表格提取

```bash
# 安装系统依赖
# macOS: brew install ghostscript
# Ubuntu: apt-get install ghostscript

# 启用表格提取
KD_TABLE_EXTRACTION_ENABLED=true
KD_TABLE_EXTRACTION_METHOD=camelot
```

支持的表格提取方法：
- **Camelot**: 基于 PDF 结构的表格提取
- **Tabula**: 基于流式布局的表格提取

表格输出格式：
- Markdown 表格
- CSV 格式
- JSON 结构化数据

## 📖 使用示例

### 上传文档

```bash
curl -X POST http://localhost:8000/api/documents/upload \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -F "file=@document.pdf" \
  -F "kb_id=YOUR_KB_ID"
```

### 语义检索

```bash
curl -X POST http://localhost:8000/api/retrieval/query \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "如何使用这个功能？",
    "kb_ids": ["YOUR_KB_ID"],
    "top_k": 5
  }'
```

### 智能问答

```bash
curl -X POST http://localhost:8000/api/chat/completions \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "这个产品有什么特点？",
    "kb_ids": ["YOUR_KB_ID"]
  }'
```

---

## 详细说明

### Layout

```text
services/
  api/          # API 服务（包含 RAG 功能）
    src/tkp_api/
      rag/  # 内置 RAG 模块（embeddings, vector_retrieval, llm_generator）
    pyproject.toml
  worker/       # Worker 服务（文档处理）
    src/tkp_worker/
    pyproject.toml
knowledge/
docs/
```

### Database initialization (SQL only)

数据库结构通过 `sql` 维护，不使用代码自动建表。

治理检查（本地/CI 通用）：

```bash
bash scripts/check_sql_governance.sh
```

规则摘要：
- 禁止 `create_all` / `metadata.create_all` 之类代码建表。
- 禁止代码式 schema 同步脚本（如 `create_all.py`、`sync_comments.py`）。
- 增量 SQL 中禁止出现外键定义（`FOREIGN KEY` / `REFERENCES`）。
- 基线统一维护在 `sql/init_all.sql`；迁移目录/锁文件若不存在会在治理脚本中跳过对应检查。

### Environment

Copy `.env.example` to `.env` in repo root and update values.

**新增必填配置：**

- `KD_OPENAI_API_KEY` - OpenAI API 密钥（必填）
- `KD_OPENAI_EMBEDDING_MODEL` - 嵌入模型（默认 text-embedding-3-small）
- `KD_OPENAI_CHAT_MODEL` - 聊天模型（默认 gpt-4o-mini）
- `KD_CHUNK_SIZE` - 文本切片大小（默认 800）
- `KD_CHUNK_OVERLAP` - 切片重叠大小（默认 200）
- `KD_RETRIEVAL_TOP_K` - 检索返回数量（默认 5）
- `KD_RETRIEVAL_SIMILARITY_THRESHOLD` - 相似度阈值（默认 0.7）

配置治理（启动前校验）：
- 当未配置 `KD_AUTH_JWKS_URL` 时，`KD_AUTH_JWT_SECRET` 必须至少 32 字节。
- 当 `KD_STORAGE_BACKEND=minio|oss` 时，`KD_STORAGE_ENDPOINT/KD_STORAGE_ACCESS_KEY/KD_STORAGE_SECRET_KEY/KD_STORAGE_BUCKET` 必填。
- `KD_RAG_BASE_URL` 配置时必须是合法 `http(s)` URL，且 `KD_INTERNAL_SERVICE_TOKEN` 不能为空白。
- `KD_OPENAI_API_KEY` 必填（Worker 与 API 内置 RAG）。

### Local Stack

推荐使用 Docker Compose 拉起本地依赖与服务：

```bash
docker compose up -d
```

查看日志：

```bash
docker compose logs -f api worker postgres redis
```

停止全栈：

```bash
docker compose down
```

说明：
- 编排文件：`docker-compose.yml`。
- 数据库初始化脚本：`sql/init_all.sql`（通过 volume 挂载自动执行）。

### API Tests

统一入口脚本：

```bash
bash scripts/test_api.sh --suite full --mode postgres
```

常用场景：

```bash
bash scripts/test_api.sh --suite smoke --mode sqlite
bash scripts/test_api.sh --suite permissions --mode sqlite
bash scripts/test_api.sh --suite all --mode postgres
```

### Production-like E2E

验证真实数据面闭环（`API -> Worker -> 内置 RAG`，依赖 `Postgres + Redis + MinIO`）：

```bash
PYTHONPATH=services/api/src .venv/bin/python -m pytest tests/e2e/test_prod_data_plane_http.py -q
```

说明：
- 测试默认访问 `TKP_E2E_API_BASE_URL`（默认 `http://127.0.0.1:18000`）。
- 当目标 API 不可达时，测试会自动 skip，避免本地环境误失败。

### Runtime Ops

新增运行态指标接口（租户 owner/admin 可访问）：

- `GET /api/ops/ingestion/metrics`
- `GET /api/ops/ingestion/alerts`
- `GET /api/ops/retrieval/quality`
- `GET /api/ops/slo/mvp-summary`
- `POST /api/ops/retrieval/evaluate`
- `POST /api/ops/retrieval/evaluate/runs`
- `GET /api/ops/retrieval/evaluate/runs`
- `GET /api/ops/retrieval/evaluate/runs/{run_id}`
- `GET /api/ops/retrieval/evaluate/compare`
- `PUT /api/ops/quotas`
- `GET /api/ops/quotas`
- `GET /api/ops/quotas/alerts`
- `GET /api/ops/cost/summary`

返回维度：
- 入库任务分状态计数（queued/processing/retrying/completed/dead_letter）
- 积压量（backlog）
- 窗口失败率（dead_letter / terminal）
- 平均与 p95 入库耗时
- 疑似卡住任务数（processing 且心跳超时）
- 规则化告警状态（ok/warn/critical）与阈值对比
