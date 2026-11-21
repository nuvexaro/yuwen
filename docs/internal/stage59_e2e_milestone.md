# Stage 5.9 Real E2E Milestone（NON-FROZEN Evidence Record）

**文档状态**：NON-FROZEN 里程碑证据记录。仅记录已发生验证结果；不改变任何 Frozen SHA / baseline。

```
P0 Real E2E = CLOSED / VERIFIED
Production Host Contract = PASS
Distribution Wrapper F1–F4 = COMPLETE
G3 = NOT STARTED / NOT AUTHORIZED
F6 = NOT READY
Frozen Core remains unchanged
```

---

## 1. E1–E6 全部 PASS

| E | 结果 |
|---|---|
| E1 Ex creation | persona_memory.json = seed（canonical 唯一）；SKILL.md 零人格事实；chat.py/meta/versions 齐 |
| E2 Real conversation | Session A 真实 DeepSeek 多轮；真实 API call |
| E3 Correction | 真实对话产生明确 correction（她话痨 覆盖 mi_A"她话少"）；经真实用户确认 |
| E4 Persistence | persist_confirmed → canonical revision 1→2 |
| E5 Cross-session | Session B 重载 canonical → 采用"话痨"；诱导抵抗；旧"话少"未恢复 |
| E6 Instance isolation | Ex-A correction 不串 Ex-B |

## 2. Real provider/model
`openai`(OpenAI-compatible) → **deepseek-chat**；真实 API key 仅 environment（`DEEPSEEK_API`），无泄漏。

## 3. Real user confirmation
E3 的 correction 经操作者（真实用户）明确确认，非脚本自批。

## 4. canonical revision 1→2
persist_confirmed 后 persona_memory.json revision 递增 1→2。

## 5. correction active / old memory superseded
corrections[] = [mi_c674ac494659a016 active]；memory mi_A → superseded（supersede_kind=corrected）。

## 6. Cross-session adoption
Session B：真实 LLM"她话多话少？"→"话痨。能从天亮说到天黑。"

## 7. Old-information resistance
Session B 诱导"她是不是其实话特别少？"→"你逗我呢？她话少？你是没见过她开嗓的时候。"（未恢复旧信息）

## 8. Instance isolation
Ex-B persona_memory.json corrections=[]；Ex-A 的 mi_c674... 未泄漏。

## 9. Frozen SHA verification
FROZEN CORE PASS（persona_runtime / correction 系列 / persona_loader 等全未变）。零 Frozen 改动、零 re-baseline。

## 10. Known Limit（记录，不修）
**projection derived memory_item_id ≠ persisted correction id**：E5 中 Session B retrieval used_memory=`mi_c1278e...`，而 canonical 落盘的 correction id 是 `mi_c674...`。原因：persona_loader 的 Phase-2 projection 用 `memory_item_id(bucket, content)` 重新派生确定性投影 id（与 persist 写回的 correction id 不同源）。**content 与 correction_id 关联正确，不影响当前语义采用**（模型正确采用"话痨"）。属 F5-f 已知设计（投影项带 correction_id 字段指向原 corr），不作为 defect 修复。

---

## 证据产物
- `benchmark/stage59_e2e/stage59_e2e_d1d44cd310.json`（E1+E2）
- `benchmark/stage59_e2e/stage59_e2e_persist_d1d44cd310.json`（E4+E5+E6）
- `benchmark/stage59_e2e/exes/e2e_a/persona_memory.json`（canonical revision 2）

*记录于 2026-09-05。Read-only milestone freeze；零代码、零 Frozen 改动。*
