# TKP 产品化路线图（2026-03）

## 目标定义
- 目标：从“技术 MVP”进入“可上线产品”阶段。
- 当前判断：
  - 技术 MVP：已达标（核心链路可用、可观测、可回归）。
  - 产品化目标：约 50%-55%。

## 阶段规划

### Phase 1：质量基建（1-2 周）
范围：
- 评测任务持久化（评测记录/版本/配置/结果快照）。
- 评测历史对比（当前 vs 基线）。
- CI 增加“关键评测集不回退”门禁。

交付标准（DoD）：
- 可查询历史评测记录与趋势。
- CI 中出现质量回退时阻断合并。
- 至少 1 套核心评测集持续可跑。

### Phase 2：控制面产品化（2-4 周）
范围：
- 配额与限流（tenant/workspace 维度）。
- 基础成本计量（检索请求、token、agent run）。
- 策略中心 v1（角色+资源策略统一视图）。

DoD：
- 可配置配额，超限有明确错误码与告警。
- 成本数据可按租户查询。
- 策略变更具备审计与回滚能力。

### Phase 3：运营面产品化（2-3 周）
范围：
- 运营后台 API（概览、租户健康、成本榜单）。
- 异常诊断与工单化（dead-letter 与高失败率场景）。
- 告警分级与通知通道（先 webhook，后 IM）。

DoD：
- 运维可在 10 分钟内定位主要故障来源。
- 关键告警具备自动通知。
- 支持按租户排障闭环。

### Phase 4：上线准备（2 周）
范围：
- 发布策略（灰度/回滚/变更审计）。
- 数据安全与合规最小集（RLS、脱敏、删除证明流程）。
- SLA/SLO 对外口径与运行手册。

DoD：
- 有明确上线清单与回滚演练记录。
- 安全基线通过。
- 生产值班与应急手册可执行。

## 本周开工（立即执行）
1. 设计并落地评测记录表（`retrieval_eval_runs` / `retrieval_eval_items`）。
2. 新增接口：
   - `POST /api/ops/retrieval/evaluate/runs`
   - `GET /api/ops/retrieval/evaluate/runs`
   - `GET /api/ops/retrieval/evaluate/runs/{run_id}`
   - `GET /api/ops/retrieval/evaluate/compare?baseline_run_id=&current_run_id=`
3. 在 `scripts/pre_commit_ci_gate.sh` 增加关键评测门禁（先 sqlite 跑核心集）。

## 风险与前置
- 风险：评测样本质量不足会导致误判。
- 风险：sqlite 与 postgres 检索特性差异会影响阈值。
- 前置：确定“核心评测集”维护流程（谁更新、何时更新、回归门槛）。
