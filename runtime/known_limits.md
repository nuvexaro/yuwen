# Stage 5.7 Runtime — Known Limits（MVP）

记录 5.7 实现过程中发现的冻结结构边界与 MVP 取舍。不修改冻结文件。

## 冻结结构相关（复用 5.5/5.6 记录，runtime 消费侧再确认）

- persona claim 无独立 status/supersede（P1-B）：runtime 无法从 schema 直接读"某 persona claim 已被纠正"；
  只能经顶层 corrections + memory history 推断。correction_runtime 只做 session 级 overlay + new claim_id，
  跨 session 持久需异步 5.5 rebuild。
- corrected_value 双层 provenance（P1-C）：runtime 的 correction overlay 把 corrected value 写入 session
  corrections_made + new claim_id，但不伪造 evidence 指向旧候选。
- candidate correction 不反写派生 claim（P2-A）：runtime 仅对 L2 首个 correction-able claim 做 overlay，
  不做全量反写。

## MVP 取舍

- **retrieval**：规则 scorer（term overlap + valid_period），无向量；对复杂语义查询召回偏弱。接口可注入 scorer。
- **reality_boundary**：detect 用相对年/绝对年与 memory 年份碰撞；对非时间类事实冲突（如地点同名）未覆盖。
- **proposal**：只在"用户陈述句 + 长度/情绪启发式"下产生；不自动确认，需后续走 5.2–5.5。
- **correction target**：MVP 只纠正 L2 speech_style 里第一个可纠 claim；不做用户选择目标的多候选路由。
- **session**：file-backed（每轮整存）足够 MVP；无并发/分片。
- **LLM gateway**：仅 mock/简单 adapter；未接真实供应商（无 key）。
- **runtime 语义评测**：Persona Fidelity / Overreach 等需 5.6 HUMAN gold；本 MVP 提供 determinism + reality +
  retrieval P/R 的 AUTO 断言，语义分待真实 LLM + 人工标注。

## 未来（不进 5.7）

- vector retrieval、session 到长期 memory 的自动确认策略、多 persona 并发、真实 LLM provider、
  可解释的 reality 事实图（非仅年份）。

## Stage 5.9-B / F5-d（retrieval projection）Known Limit

- **Long-session + zero lexical overlap + weak/unresolved referent 的 recall 当前无法保证。**
  该场景可能同时涉及 keyword retrieval 与长会话 referent resolution，因此不得把失败原因
  确定性归因于单一模块。真实 LLM 验证 R-D4-3a：correction("她话痨") 后插入 ≥6 个无关 turn，
  最终以"你觉得她好相处吗？"询问（与纠正内容零字面重叠）→ 模型丢指代（"哪个她？"），
  retrieval 未召回。**这是当前产品边界，不属于 F5-d implementation defect。**
- **semantic / vector / embedding retrieval 与长会话 referent resolution 属于未来独立能力**，
  不在本阶段授权范围；本阶段不引入、不修改 memory_retrieval.py 的 scoring 算法。
- F5-d 冻结状态：Correction → Retrieval Projection / Cross-topic recall / Naturalness improvement /
  Persona isolation / Conflict resistance 均 PASS；Long-session zero-overlap referent recall = KNOWN LIMIT。

