# 代码导读（先看这个）

这份导读按“一个请求从进到出”的顺序说明，不按目录树硬读。

## 1. 登录与租户上下文

入口文件:
- `services/api/src/tkp_api/dependencies.py`
- `services/api/src/tkp_api/core/security.py`

你重点看 3 个函数:
1. `parse_authorization_header`：解析 JWT，拿到 `sub/email/iss`。
2. `ensure_user`：把外部身份映射到本地 `users` 表。
3. `get_request_context`：从 JWT 的 `tenant_id` 构建租户上下文，并校验 `tenant_memberships`。

理解这层后，后续所有路由里看到 `ctx=Depends(get_request_context)` 就不抽象了。

## 1.1 工作空间权限层

新增文件:
- `services/api/src/tkp_api/models/workspace.py`
- `services/api/src/tkp_api/api/workspaces.py`
- `services/api/src/tkp_api/services/authorization.py`

权限链是:
1. 用户先是租户成员（tenant_memberships）
2. 用户再是工作空间成员（workspace_memberships）
3. 用户还要有 KB 成员关系（kb_memberships）才能读 KB
4. 文档权限继承 KB 权限

## 1.2 前端权限契约（菜单/按钮/功能）

接口:
- `GET /api/permissions/me`
- `GET /api/permissions/ui-manifest`

联调建议:
1. 登录后先调用 `/api/permissions/ui-manifest`，缓存 `version`。
2. 用 `menus/buttons/features[].allowed` 控制展示与禁用。
3. 若后端返回的 `version` 变化，前端触发权限配置热更新（重新拉取 manifest）。
4. 前端仅做展示控制；后端仍以 `require_tenant_action` 与资源范围校验为准。

## 2. 文档上传链路

入口文件:
- `services/api/src/tkp_api/api/documents.py`

`upload_document` 的顺序:
1. 权限校验（tenant 角色）
2. 判断是新文档还是已有文档新版本
3. 原文件落盘（`services/api/src/tkp_api/services/storage.py`）
4. 写 `document_versions`
5. 写 `ingestion_jobs`（`services/api/src/tkp_api/services/ingestion.py`）
6. 写审计日志（`services/api/src/tkp_api/services/audit.py`）

这就是“控制面”职责，API 只负责入库和入队，不做重处理。

## 3. Worker 消费链路

入口文件:
- `services/worker/src/tkp_worker/main.py`

主循环:
1. `_claim_next_job` 抢任务（带锁）
2. `_process_job` 读取 object_key + 切片 + 写 `document_chunks`
3. `_mark_success` 或 `_mark_failure`

失败策略:
- 次数没超：`retrying` + `next_run_at`
- 次数超限：`dead_letter`

## 4. 检索与问答

入口文件:
- `services/api/src/tkp_api/api/retrieval.py`
- `services/api/src/tkp_api/api/chat.py`
- `services/api/src/tkp_api/services/retrieval.py`

目前是可运行基线:
- 从 `document_chunks` 检索匹配片段
- chat 返回答案 + citations

你后续接入真正 embedding/rerank/LLM，只需要替换 `services/retrieval.py` 和 `chat.py` 的组装逻辑。

## 5. 数据模型对应关系

模型文件:
- `services/api/src/tkp_api/models/tenant.py`
- `services/api/src/tkp_api/models/knowledge.py`
- `services/api/src/tkp_api/models/audit.py`

最关键 4 张业务表:
- `documents`：文档主记录
- `document_versions`：版本
- `ingestion_jobs`：异步处理任务
- `document_chunks`：可检索内容

先把这 4 张表的字段和状态流转看懂，整个系统就通了。
