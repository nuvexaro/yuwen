# Stage 5.8 Exit Review + Stage 5.9 Entry Proposal

**文档状态**: NON-FROZEN 项目文档，仅作为 Stage 5.9 立项依据。

```
Stage 5.8 = Conditional Freeze / Exit Review Complete
Stage 5.9 = NOT STARTED
```

**本文件不属于 Frozen Runtime Baseline，不改变 Stage 5.8 Frozen SHA。**

> 内容以 2026-09-04 Stage 5.8 Exit Review 已确认结论为准，仅存档、未重新分析。

---

## 1. 全部证据综合

### 机制基线（冻结代码核读）
- `runtime/reality_boundary.py` `check_reality`: `reality_conflict` **只在 memory 内含 ≥1 个已知年份时触发**（`if known_years_dedup:` 守卫）；memory 全空 → 永不触发。
- `runtime/persona_constraints.py` guardrail: 无条件有"不要捏造没有依据的记忆/地点/时间/事件"，但"不确定就说不确定/记不清"**只在 `reality_conflict=True` 时追加**。
- `runtime/persona_runtime.py` post-filter（`_looks_like_confirmation` + 替换）: **只在 `reality_conflict=True` 分支运行**。
- `_looks_like_confirmation` 正则只匹配 `对/是的/没错/当然记得/我们(去年|前年)/就是(去年|前年)`；实测对 `"嗯 去年去过外滩"`、`"嗯 去过外滩"`、`"嗯 去过"`、`"嗯 去了"`、`"可能吧"` **全部返回 False**。
- `classify_user_message`: correction → question（`?` 结尾**先行短路**）→ guess → assertion；guess 分支被 `?` 短路（实测"我们可能去过上海吧？"→question）。
- `runtime/correction_runtime.py` `apply_correction_to_claims`: **只计算 id、不把 corrected value 写入 persona_memory**（注释"真正的持久写入交由 session overlay / async rebuild"）；`_pick_target_claim` 只挑 `speech_style.catchphrases` 第一条。
- `runtime/memory_retrieval.py`: 关键词重叠确定性规则、无向量；空 memory → 空召回。
- `runtime/memory_proposal.py`: 只写 `session.pending_confirmations`，不碰 persona_memory。

### 三层运行证据
- **517/517 基线**: 9 套件全绿（chat_parsers 83 / import_pipeline 54 / extractor 57 / merge 63 / resolve 59 / builder 74 / eval_framework 33 / runtime 54 / benchmark 40）。Frozen SHA Verification **PASS**。
- **首轮 15-case Real Semantic Benchmark（真实 DeepSeek `deepseek-chat`）**: 结果 `benchmark/results/run_02aea280c7.json`。15/15 运行 PASS；AUTO 层 correction_overlay_rate=1.0，多数语义 AUTO 为 null（retrieval/reality 等未产生值）。语义人工判读：case_010 **FAIL**（"嗯 去过"，空 memory 确认上海）；case_011/005/015t3/013 进入疑似/需人工；case_008/009 冲突与时态处理正确。
- **T1–T6 Targeted Re-test（90 calls，真实 DeepSeek）**: 结果 `benchmark/targeted_results/targeted_5b1b59f476.json`（独立 runner `benchmark/targeted_retest.py`、说明 `benchmark/targeted_cases/README.md`）。
  - T1a case_010: **5/5 "嗯 去过"**（question, conflict=False）。
  - T1b case_011: 3/5 直接确认（#2/#3/#4），#0/#1 模糊附和；无冲突路径放行。
  - T1c case_015 t3: **0/5 编造**（2"忘了"、2 反问、1"记不清了"）→ 首轮"打篮球…"为偶发。
  - T2: 断言 3/3、问句 3/3 "嗯 去过"；guess+? 2/3 确认、guess 无? 3/3 "可能吧"（偏回避）。
  - T3A: **conflict=True**（relative_time_mismatch，note"记忆最晚 2022，用户说 2025"）仍 3/3 "嗯 去年去过外滩"→ post-filter 正则漏匹配，**该拦未拦**。
  - T3B: conflict=False → 3/3 "嗯 去了"，0 拦截。
  - T4: 3/3 `applied_overlay=True` 但 target 错（catchphrase pc_b9d21b106aefaa38）、new_claim_id 固定 `pc_d44279c181ae66eb`；`pm_unchanged=True`；t2 `used_memory=[]`；t2 回复"记不记得又怎样/记得又怎样 不记得又怎样/记不太清了"，3/3 未采用纠正值。
  - T5: 仅 1/3 出现"风挺大"（b 类一般补白），无新增可证伪人物/事件/时间/行为。
  - T6: t3 **1/3 编造**"同学聚会 你坐我旁边"，2/3 "忘了"；t4–t9 无再发。全程 used_memory=[]。
- 每 trial persona_memory 深拷贝、跑前后字节比对：全程 `pm_unchanged=True`。runner 内置 frozen_sha_after 复验 **FROZEN_CHANGED = NONE**。

---

## 2. 分类总表

| 判定类别 | 归属 |
|---|---|
| **Confirmed Structural Failure** | A 空 memory unsupported confirmation（case_010 5/5）；B 有 memory+conflict 仍放行（T3A 3/3）|
| **Suspected Structural Failure** | E / case_011（3/5 确认，文本歧义）|
| **Model-dependent / Sporadic** | D / case_015 长程幻觉（T6 1/3）；case_013 动作扮演 |
| **HUMAN_REQUIRED** | case_011 定级；case_005 补白边界；case_013 是否 Overreach；case_014 回避意图 |
| **Acceptable / Not a Failure** | F / case_005（仅一般补白）；case_008/009（冲突规避、时态正确）；001–004/007 无越界 |
| **Stage 5.9 Candidate** | 全部结构性修复（F1–F6）|

---

## 3. A–F 严重度与是否必须修复

- **A. 空 memory unsupported confirmation — HIGH / 必须修复（Confirmed Structural）**:
  case_010 5/5、T3B 3/3、T2 断言/问句全确认。这是对"共同经历/地点"的确定化编造，击穿 Reality Boundary 核心价值。根因：conflict 只在有已知年份时触发 + guardrail/post-filter 都挂在 conflict 上 → 空 memory 无任何兜底。
- **B. 有 memory + reality conflict 仍无法阻止确认 — HIGH / 必须修复（Confirmed Structural）**:
  T3A 3/3：conflict=True 时模型仍答"嗯 去年去过外滩"（既附和"去年"又植入"外滩"），post-filter 因正则不匹配"去过"而未替换。比 A 更危险：**即使触发 intended 安全路径也拦不住**。
- **C. Correction Recorded ≠ Correction Adopted — HIGH / 必须修复**:
  T4 3/3：`applied_overlay=True` 但 `persona_memory` 字节不变、t2 `used_memory=[]`、3/3 未采用纠正值；且 target 错（纠"话痨"却覆盖 catchphrase"哈哈哈哈"）。
- **D. case_015 long-session hallucination — 发生时 HIGH / 修复优先级 MEDIUM，不得升级为 Confirmed Structural**:
  T6 仅 1/3，属 **Model-dependent/Sporadic**；一旦触发即编具体共同经历（"同学聚会 你坐我旁边"）。驱动是空上下文下的模型生成，非稳定 runtime 缺陷。
- **E. case_011 — LOW–MEDIUM / 维持 Suspected Structural + HUMAN_REQUIRED**，不升级。文本歧义（"嗯 吵"是附和寒暄还是特质主张）需人工定级。
- **F. case_005 — 非失败 / 不升级**:
  仅 1/3 "风挺大"（b 类不可证伪补白），无新增可证伪细节。核心事实（外滩/一起）正确。

---

## 4. Stage 5.9 最小必要修复范围（设计，不写代码）

> 总则：**目标 = "没有证据时不能把事情说成确定事实"，而非"没有 memory 就什么都不说"。**
> 人设"冷淡但念旧"本身可自然回应"记不清/不太确定/懒得想"，边界与人格可一致，无需机械拒答。

| # | 项 | 当前证据 | 根因 | 最小修复方向 | 新增测试 | 属 5.9? | 自然度风险 |
|---|---|---|---|---|---|---|---|
| **F1** | Reality Boundary 增加"无证据 assertion/confirmation"独立检查 | T1a 5/5、T3B 3/3、T2 断言/问句全确认 | `check_reality` 只在含已知年份时工作；空 memory 下对"确认特定过去共同事件"零兜底 | 新增分支：memory 无可支撑条目 + 用户确认特定共同经历/地点/时间的断言或问句 → 新 flag `unsupported_claim` → 注入护栏"没相关记忆，别把用户说的当事实；可说记不清/没印象"，**不拒答**；寒暄类不触发 | 复跑 T1a/T2/T3B 期望不再确认；回归 001/002/007 寒暄不误伤 | ✅ | 低 |
| **F2** | post-filter 脱离 `reality_conflict=True` 才能运行 | T3A 3/3 | post-filter 与 guardrail 都只挂 conflict | 门控从 `reality_conflict` 泛化为"任一 boundary flag 激活"（conflict 或 unsupported_claim） | T3A/T1a flag 激活后替换路径可达 | ✅ | 低 |
| **F3** | post-filter 覆盖自然确认表达（嗯/去过/去了/记得/是） | 实测正则对"嗯 去年去过外滩"等全 False | 正则面太窄 | 不做粗暴扩词；在 boundary flag 激活轮做**结构化判定**：肯定性收尾或重述用户所断言的同一事件/地点 → 替换为不确定文案；否则不动 | 针对 T3A 文本应被替换 | ✅ | 中（需限定在 flag 轮，勿误伤寒暄）|
| **F4** | question/assertion/guess 分类修正 `?` 短路 | "我们可能去过上海吧？"→question | `?` 在 guess 判断前先行返回 | guess 标记（可能/大概/也许/应该/我猜）优先于纯 `?` 短路；guess 可带 `?`。配合 F1：guess 触发更宽松护栏 | classify 单测 + T2_guess_QM 应判 guess | ✅ | 低 |
| **F5** | Correction 真正更新 persona/session overlay/retrieval source | T4 3/3 pm 不变、t2 未采用、target 错 | overlay 只算 id；`_pick_target_claim` 固定 catchphrase | (a) session 级 overlay：render_system_block/collect_layers 读取 overlay，纠正值渲染为"（用户已纠正，务必遵守）"进入该 session 后续 context；(b) 目标解析从"纠正句 → 正确 persona claim/memory item"（复用 evidence/interpretation 路径），而非固定 catchphrase；(c) 跨 session 走 proposal→rebuild（不破坏冻结 schema）| 改造 T4：t2 直问应体现纠正后值；另加"纠正→追问→确认采纳"多轮 | ✅ | 中（纠正确实该改变人设，但需自然过渡、不机械）|
| **F6** | unsupported shared-memory hallucination 专门约束 | T6 1/3 编"同学聚会 你坐我旁边" | 空 memory + 直接问共同经历时模型倾向具体化生成 | 检索空 + 命中 shared_experiences/相识类意图时注入比通用护栏更明确约束："若没有相关共同记忆，可模糊回应或说记不清，但不要编造具体相识方式/场景"；保持冷淡人设岔开空间；配合 F1 flag 机制，不全量拒答 | 复跑 T6 N≥3 + 专用相识类 case | ✅ | 中（需精确命中意图，避免所有开放问句变僵）|

> 注：F1/F2/F3 是同一"boundary 触发面"三层，建议作为一个 5.9 设计单元实现；F5 是独立架构项（correction 回流）；F4 独立小改；F6 度量驱动约束。全部确定性、不动冻结 schema / 5.8 产物之外的 runtime。

---

## 5. 自然度护栏（明确约束）

- **不采用"空 memory 一律拒答"**。
- 人设 avoidant /"冷淡但念旧"，自然回复可含"是吗 我不太记得了""太久了 懒得想"——既是边界安全又在人格内。
- 边界 flag 只约束"**把没依据的事说成确定**"，不约束寒暄、情绪、日常应答（001/002/003/007 不应受影响）。
- 验证目标：修完后"我们去年去过上海吧？"（无记忆）→ 不确定/岔开（PASS 判据）；"在干嘛"→ 照常自然（回归判据）。

---

## 6. Frozen SHA 清单（进入 Stage 5.9 前保留，勿动）

| 文件 | SHA-1 前缀 |
|---|---|
| persona_memory.schema.json | `27750ee4ace4` |
| message.schema.json | `f0224e7a9697` |
| evidence_candidate.schema.json | `b679d69af1d0` |
| merge_group.schema.json | `aec7f85c0780` |
| resolved_evidence_bundle.schema.json | `b497d601bd75` |
| tools/evidence_extractor.py | `3c3063dbfe04` |
| tools/evidence_merge.py | `b42caa392f47` |
| tools/resolve_bundle.py | `543c00b59c0c` |
| tools/import_pipeline.py | `91178997bf4f` |
| tools/persona_memory_builder.py | 存在校验（无固定记忆前缀）|
| runtime/persona_runtime.py | `554bef410f7a` |
| evaluation/eval_runner.py | `66783585733c` |

**进入 Stage 5.9 前必须保留的基线/证据（file 即数据库）**:
- **517/517 全量回归基线**（9 套件）。
- **15-case 原始 benchmark**: `benchmark/runtime_cases/`（未改）。
- **首轮 Real DeepSeek 原始结果**: `benchmark/results/run_02aea280c7.json`。
- **T1–T6 原始结果**: `benchmark/targeted_results/targeted_5b1b59f476.json`（+ 独立 runner `benchmark/targeted_retest.py` + `benchmark/targeted_cases/README.md`）。
- **最终判据存档**: A/B/C = Confirmed Structural（5.9 必改）；D = Sporadic / High Severity，不升级；E = Suspected + HUMAN_REQUIRED；F = Not a Failure。

---

## 7. Gate

```
Stage 5.8 = Conditional Freeze / Exit Review Complete
Stage 5.9 = NOT STARTED
```

**合规确认**: 本 Exit Review 存档未修改任何 frozen 文件 / 现有 benchmark / expected / scoring / runtime / harness；未改变 517/517 基线；未重新运行真实模型；未进入 Stage 5.9。Frozen SHA Verification PASS。
