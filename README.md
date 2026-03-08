# TKP 平台后端

TKP 是一个面向企业知识管理与智能问答的多租户平台后端。
它帮助团队把分散文档沉淀为可检索、可治理、可追踪的知识服务能力。

## 平台用处

- 搭建企业级知识库：统一管理文档、版本与归属
- 提供智能检索与问答：支持语义检索、引用回溯与对话式问答
- 支撑多租户业务：租户、工作空间、知识库三级隔离
- 满足治理与审计需求：删除流程、保留策略、反馈回放、操作追踪
- 提供运维可观测能力：健康检查、指标导出、运行态接口

## 核心能力

- API 服务（`services/api`）：认证鉴权、资源管理、检索/问答、治理与运维接口
- Worker 服务（`services/worker`）：文档解析、切片、向量化、入库任务处理
- 存储与检索：PostgreSQL + pgvector，支持接入 Redis、MinIO/OSS、Elasticsearch

## 快速启动（本地）

1. 准备环境变量

```bash
cp .env.example .env
```

2. 启动测试依赖环境（PostgreSQL + Redis + 初始化库表）

```bash
bash scripts/test_env_up.sh
```

3. 启动 API

```bash
DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:55432/tkp_api_test \
REDIS_URL=redis://127.0.0.1:56379/0 \
STORAGE_BACKEND=local \
STORAGE_ROOT=./.storage-dev \
PYTHONPATH=services/api/src \
.venv/bin/python -m uvicorn tkp_api.main:app --host 127.0.0.1 --port 8000
```

4. 启动 Worker（需要处理文档入库时）

```bash
DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:55432/tkp_api_test \
STORAGE_BACKEND=local \
STORAGE_ROOT=./.storage-dev \
PYTHONPATH=services/worker/src \
.venv/bin/python -m tkp_worker.main
```

## 常用入口

- 接口文档：`http://127.0.0.1:8000/docs`
- 存活检查：`GET /api/health/live`
- 就绪检查：`GET /api/health/ready`
- 指标接口：`GET /api/metrics`

## 目录

```text
services/api      # 后端 API 服务
services/worker   # 入库处理 Worker
scripts           # 本地测试与环境脚本
sql               # 数据库初始化脚本
docs              # 设计与实现文档
```

## 说明

若与前端本地联调，建议前端使用 Vite 代理（`/api` -> `http://127.0.0.1:8000`），避免跨域问题。
