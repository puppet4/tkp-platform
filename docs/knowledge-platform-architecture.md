# 产品级多租户知识平台架构设计

版本: v1.0  
状态: Draft  
更新时间: 2026-02-27

## 1. 背景与目标

本项目目标是建设一个可产品化的知识平台，支持:

- 多租户隔离
- 多用户协作
- 多知识库管理
- 高质量 RAG
- 可控 Agent 编排
- 可观测、可审计、可扩展

该平台不是单次 Demo，而是可持续演进的基础设施层。

## 2. 设计原则

1. 租户隔离优先。所有核心设计围绕 tenant boundary 展开。
2. 控制面与数据面分离。管理操作和在线推理解耦。
3. 同步查询与异步处理解耦。上传处理不阻塞在线问答。
4. 模型与存储可插拔。避免供应商锁定。
5. 默认可审计。关键动作必须有追踪和审计记录。
6. 渐进式复杂度。先保证正确边界，再扩展能力。

## 3. 范围定义

### 3.1 包含

- 租户、用户、组织成员与权限管理
- 知识库、文档、版本、标签和元数据
- 文档接入、清洗、切片、向量化、索引
- 检索、重排、生成、引用归因
- Agent 工具编排与执行治理
- 运维监控、审计、评测和成本分析

### 3.2 不包含

- 私有模型训练平台
- 全量 BI/报表系统
- 通用低代码工作流平台

## 4. 逻辑架构

```text
+----------------------- Experience Layer ------------------------+
| Web Console | OpenAPI/SDK | Webhook | CLI                     |
+-------------------------+---------------------------------------+
                          |
+----------------------- Control Plane ---------------------------+
| IAM | Tenant Mgmt | KB Mgmt | Policy | Quota/Billing | Audit  |
+-------------------------+---------------------------------------+
                          |
+------------------------- Data Plane ----------------------------+
| Ingestion | Parser | Chunking | Embedding | Index | Retrieval  |
| Rerank | Generation | Citation | Conversation Memory           |
+-------------------------+---------------------------------------+
                          |
+---------------------- Agent Plane ------------------------------+
| Planner | Tool Registry | Executor Sandbox | Guardrail         |
+-------------------------+---------------------------------------+
                          |
+------------------------ Ops Plane ------------------------------+
| Metrics | Traces | Logs | Eval | Drift Detection | Alerting    |
+---------------------------------------------------------------+
```

## 5. 服务清单与职责

| 服务 | 核心职责 | 关键输出 |
|---|---|---|
| IAM Service | 用户认证、组织成员、角色授权 | identity token, membership |
| Tenant Service | 租户生命周期、隔离等级、配额 | tenant policy |
| Knowledge Service | 知识库/文档管理、版本管理 | kb/doc metadata |
| Ingestion Orchestrator | 任务编排、幂等、重试、死信 | ingestion job state |
| Parser Service | 文档解析、图片 OCR、结构提取 | normalized doc blocks |
| Chunking Service | 结构化切片、父子块构建 | chunk set |
| Embedding Gateway | 模型路由、缓存、限流、降级 | vectors |
| Index Service | 向量与全文索引写入/更新 | searchable index |
| Retrieval Service | 召回、权限过滤、重排、聚合 | ranked chunks |
| Generation Service | Prompt 装配、答案生成、引用 | answer + citations |
| Agent Orchestrator | 计划执行、工具调用、风险治理 | task execution trace |
| Eval Service | 离线评测、线上反馈回放 | quality reports |
| Audit Service | 安全审计、行为追踪、合规留存 | immutable audit events |

## 6. 多租户与权限模型

### 6.1 租户模型

- Tenant 表示一个组织数据边界。
- User 表示账号主体。
- Membership 表示 User 在 Tenant 内的角色。

关系:

- 一个 Tenant 下可有多个 User。
- 一个 User 可属于多个 Tenant。

### 6.2 授权分层

1. Tenant 级角色: `owner/admin/member/viewer`
2. 知识库级角色: `kb_owner/kb_editor/kb_viewer`
3. 资源级策略: `document/chunk/tool` 可附加 ABAC 条件

### 6.3 权限执行红线

1. 所有请求都必须携带 `tenant_id` 上下文。
2. 任何读写必须在 SQL 层携带 `tenant_id` 过滤条件。
3. 检索必须先权限裁剪，再召回。
4. 严禁“先查全量再代码过滤”。

## 7. 数据模型设计

核心实体建议:

- `tenants`
- `users`
- `tenant_memberships`
- `knowledge_bases`
- `kb_memberships`
- `documents`
- `document_versions`
- `document_chunks`
- `chunk_embeddings`
- `retrieval_logs`
- `conversations`
- `messages`
- `agent_runs`
- `audit_logs`

关键字段约束:

1. 全部业务实体带 `tenant_id`。
2. 文档与分块有 `version` 字段，支持重建索引。
3. 分块保留 `source_ref`、`title_path`、`token_count`。
4. 审计日志包含 `actor`, `action`, `resource`, `before/after`, `ip`。

## 8. 存储与索引架构

### 8.1 存储分层

- 关系数据: PostgreSQL
- 对象数据: S3/MinIO
- 向量数据: pgvector 或 Milvus/Qdrant
- 全文索引: OpenSearch/Elasticsearch
- 缓存和限流: Redis
- 异步总线: Kafka 或 RabbitMQ

### 8.2 检索策略

- 默认 Hybrid: `BM25 + Vector`
- 可选 reranker: cross-encoder
- 支持 query rewrite 与去噪
- 支持 parent-child chunk 合并返回

## 9. 文档接入与处理流水线

标准流程:

1. 文档上传入对象存储
2. 创建 ingestion job
3. 解析文档结构
4. 文本清洗与规范化
5. 按规则切片
6. 生成 embedding
7. 写入向量与全文索引
8. 构建元数据倒排
9. 发布可检索版本

保障机制:

- 幂等键: `tenant_id + doc_id + version`
- 任务重试与死信队列
- 每步可重放与可观测

## 10. RAG 架构规范

在线查询链路:

1. Query 预处理: 语言识别、纠错、改写
2. 权限过滤: 按 tenant + kb + ACL 裁剪范围
3. 多路召回: vector / keyword / metadata filter
4. 重排: relevance + policy score
5. Context Packing: token 预算与去重
6. LLM 生成: 强制引用上下文
7. Answer Grading: 低置信度触发拒答

输出规范:

- 必须返回引用列表
- 每条引用可定位到 `doc_id/chunk_id/version`
- 记录召回轨迹用于回放

## 11. Agent 架构规范

Agent 设计为“可治理执行器”，不是自由自动化脚本。

核心组件:

- Planner: 生成任务计划
- Tool Registry: 工具描述与权限策略
- Executor: 沙箱执行与资源限制
- Guardrail: 输出安全与策略拦截
- Run State Store: 状态机与恢复点

执行流程:

1. 意图识别与任务分类
2. 生成执行计划
3. 工具授权校验
4. 执行与观察
5. 验证与收敛
6. 审计落库

安全策略:

- 工具白名单
- 网络出站控制
- 预算与速率限制
- 敏感操作双重确认

## 12. 可观测性与质量体系

### 12.1 指标体系

- 可用性: API 成功率、错误率
- 性能: P50/P95/P99 延迟
- 质量: 命中率、引用准确率、拒答准确率
- 成本: 每请求 token、向量检索成本、Agent 工具成本

### 12.2 SLO 示例

- 检索 API 可用性 >= 99.9%
- 问答端到端 P95 < 3s（不含长工具执行）
- 索引更新完成时延 P95 < 5min
- 引用覆盖率 >= 95%

### 12.3 评测机制

- 离线问答集回归
- 线上人工反馈闭环
- 数据漂移监控
- 模型版本 AB 实验

## 13. 安全与合规

1. 全链路 TLS + 静态加密（KMS）
2. 行级访问控制（RLS）与最小权限
3. PII 检测与脱敏策略
4. 数据保留与删除策略可配置
5. 全量审计日志不可篡改存储
6. 支持合规导出与删除证明

## 14. 部署拓扑建议

环境分层:

- `dev`: 单区域低成本，功能验证
- `staging`: 近生产拓扑，压测与回归
- `prod`: 多可用区，高可用配置

发布策略:

- 蓝绿/金丝雀
- 配置中心灰度开关
- 数据库迁移前向兼容

容灾策略:

- 跨可用区部署
- 关键存储定期快照
- RPO/RTO 明确目标并演练

## 15. 成本与容量治理

成本结构:

- LLM token 成本
- Embedding 成本
- 向量存储与检索成本
- 全文索引成本
- 对象存储与带宽成本

优化手段:

- 相似 query 缓存
- 热知识预检索缓存
- 分层模型路由
- 冷热索引分层

## 16. 分阶段实施路线图

Phase 1: 平台基线

- IAM + Tenant + KB + 文档入库 + 基础检索
- 审计日志 + 指标监控

Phase 2: RAG 强化

- Hybrid recall + rerank + 引用归因
- 评测体系与线上反馈

Phase 3: Agent 化

- 工具注册中心
- 可治理执行引擎
- 风险策略与预算控制

Phase 4: 企业化

- 隔离等级升级（共享 -> 独享）
- 合规与计费能力
- 多区域部署与灾备

## 17. 关键技术决策记录（ADR）建议

建议建立 `adr/` 目录，每个关键决策独立成文:

- 向量数据库选型
- 检索策略选型
- Agent 执行框架选型
- 多租户隔离等级策略
- 安全合规基线

## 18. 立项评审检查清单

1. 是否全链路强制 `tenant_id`?
2. 是否具备服务端强权限校验?
3. 是否支持文档与分块版本化?
4. 是否具备引用归因与拒答策略?
5. 是否具备可观测与审计闭环?
6. 是否具备压测、回归、灾备计划?

---

该文档用于架构评审与跨团队对齐。后续可基于本版本补充:

- C4 图（Context/Container/Component）
- 数据库 ER 图
- 关键时序图（Ingestion/Retrieval/Agent）
- API 契约与错误码规范
