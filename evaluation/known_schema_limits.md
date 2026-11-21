# Stage 5.6 Evaluation — Known Schema / Runtime Limits

本文件记录 Evaluation 暴露出的 persona_memory v1.2 / 冻结链路的**已知结构限制**。
这些不是 5.6 可修复项，也不在 5.6 修改冻结文件。列为 Future v1.3 / Future Runtime Issue。

## P1-B：persona claim 无独立 status / supersede

persona_memory v1.2 的 `claim` 没有 status / superseded / history 字段（只有
claim_id / value / evidence_ids / confidence / basis）。

影响：
- persona claim 自身不能表达"已被纠正/已被取代"的生命周期。
- 旧 persona 解释的恢复只能靠：
  - 顶层 `corrections[]`（original_value / target_id / corrected_value）
  - revision / version history（外部）
不能伪造 persona claim status / supersede 字段（v1.2 additionalProperties:false 会拒绝）。

## P1-C：corrected_value 的双层 provenance 无法在 v1.2 表达

语义："旧 evidence → old value" 与 "correction → corrected value" 是两层来源。

v1.2 `claim.evidence_ids` 只指候选。纠正后的 claim 若沿用旧 candidates 当 evidence，
会错误暗示"旧证据支持新值"。

当前最诚实的表达（已在 5.5 采用）：
- 新 claim：`value=corrected_value`、`basis=correction`、`evidence_ids=[]`
- provenance 由顶层 `corrections[]`（user_statement + corrected_value + 旧 target_id）承载

这无法在 schema 上区分"证据支持旧值 / 纠正产生新值"，属 v1.2 结构限制。

## P2-A：candidate correction 不自动反写所有派生 claim / memory

5.4 定位、5.5 overlay 只处理 persona_claim / memory_item 目标的纠正。
`target_kind=candidate` 的纠正仅记录到顶层 corrections，不自动重算所有依赖该候选的
派生 claim / memory。语义上"纠正某候选 → 其派生的解释应更新"，当前不做，
需未来 runtime / 增量重算层处理。

## 其它记录

- 5.5 builder 无 LLM 时（llm=None）为保守确定性回退：只归 memory、不产 persona（除 L0/L1 由证据驱动）。
  Evaluation 默认用该路径，保证可重复；真实 LLM interpretation 需另行注入并依赖人工评测。
