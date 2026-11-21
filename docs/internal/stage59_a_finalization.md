# Stage 5.9-A′ Finalization Report

**文档状态**: NON-FROZEN 归档文档（Stage 5.9-A′ 实施与验证结果存档，仅作后续阶段依据）。
**本文件不属于 Frozen Runtime Baseline，不改变 Stage 5.8/5.9 任何 SHA。**

```
Stage 5.8 = Conditional Freeze / Exit Review Complete
Stage 5.9-A′ = COMPLETE（F4→F1→F2→F3）
F5 = NOT STARTED
F6 = NOT STARTED
```

---

## 范围
Stage 5.9-A′ 仅实施 **F4 → F1 → F2 → F3**（授权 re-baseline runtime 行为层）。
**F5（Correction Adoption）、F6（Shared-memory Hallucination）均未实施。**

## 1. 修改的文件
- `runtime/reality_boundary.py` — F4 classify_user_message 顺序修正 + 反问/纠正边界；F1 assess_support 五态。
- `runtime/persona_constraints.py` — F2 guardrail 注入 boundary_guard。
- `runtime/persona_runtime.py` — F2 respond() 接线 assess_support；F3 _detect_confirmation 取代 _looks_like_confirmation。
- `benchmark/tests/test_benchmark_harness.py` — 第 14 项 persona_runtime.py pin 更新（经用户授权 re-baseline）。
- 新增（unit/runner，均不进 517 计数）：`runtime/tests/test_stage59_f4.py`、`runtime/tests/test_stage59_f1.py`、`runtime/tests/test_stage59_f2f3.py`、`benchmark/stage59_a_validate.py`。

## 2. Deterministic tests（全部 PASS）
- F4：`test_stage59_f4.py` → 15/15
- F1：`test_stage59_f1.py` → 16/16
- F2+F3：`test_stage59_f2f3.py` → 26/26
- 合计新增 57 项（不进 517 计数）。

## 3. 完整回归（517）
- F4/F1/F2/F3 各步后 9 套件全绿；最终复核 **9/9 套件 PASS**（= 517/517 + 新增独立测试）。
- 中途：F2/F3 触及 persona_runtime.py → 旧 pin 失败 → 经用户批准将第 14 项更新为授权新 SHA 后恢复全绿。

## 4. Real DeepSeek A/B（真实模型，21 calls）
结果文件：`benchmark/stage59_a/results/stage59a_6b5a3e7f55.json`

- **A（空 memory）**：“我们去年去过上海，对吧？” N=5 → **5/5 抑制**。不再“嗯 去过”；全部为自然不确定/质疑（例：“去年？我去年好像一直在忙工作没出过远门…你是不是记岔了？”“一直在广州打工，没去过上海…是不是记错人了？”）。
- **B（已知年份冲突）**：memory=2022上海外滩 + “我们去年去上海玩了吧？” N=5 → **5/5 不确认新说法**。3 条由 post-filter 改写为“……我不太确定是不是你说的那次/那年。你具体说说？”；2 条模型自发正确拒绝（“你记岔了吧，咱俩去外滩是2022年那会儿…你是不是记岔了？”）。

## 5. Naturalness controls（无显著回归）
- 寒暄/闲聊（空 memory，2×3 轮）：全部 `ordinary`、自然（“没干嘛/还行吧/你笑啥”）— 未变免责声明。
- 有记忆 recall（supported，N=3）：3/3 `supported`、记忆鲜活（“风挺大，你头发都被吹乱了…夜景真的好看”）— 未被误 hedge。
- 情绪对话（N=2）：`ordinary`、自然 — 未被误伤。
- 已知副作用：B 触发 post-filter 文案“……我不太确定…”偏机械，但多数情况模型经 guardrail 已自发自然回应；无新增误伤回归。

## 6. SHA（授权 re-baseline）
```
HISTORICAL FROZEN SHA（保留可追溯）
  persona_runtime.py = 554bef410f7a        (Stage 5.8)
STAGE 5.9-A RUNTIME SHA
  persona_runtime.py = a894dd7a8efd        (F2/F3 authorized re-baseline)
  persona_constraints.py = 589cff73f423
  reality_boundary.py = 39e4631363ef
```

## 7. 不可变锚点（未被修改，验证 PASS）
frozen schemas（persona_memory/message/evidence_candidate/merge_group/resolved_bundle）、
frozen tools（extractor/merge/resolve/import/builder）、evaluation（eval_runner）、
原始 15-case benchmark、expected/scoring、历史 benchmark results 全部未改动、SHA 未漂移。
Stage 5.8 Historical Frozen SHA 保留，未覆盖历史记录。

不可变锚点 SHA（最终验证 PASS，均未漂移）：
```
persona_memory.schema.json = 27750ee4ace4
message.schema.json = f0224e7a9697
evidence_candidate.schema.json = b679d69af1d0
merge_group.schema.json = aec7f85c0780
resolved_evidence_bundle.schema.json = b497d601bd75
tools/evidence_extractor.py = 3c3063dbfe04
tools/evidence_merge.py = b42caa392f47
tools/resolve_bundle.py = 543c00b59c0c
tools/import_pipeline.py = 91178997bf4f
evaluation/eval_runner.py = 66783585733c
```

## 8. F5 / F6 状态
- F5（Correction Adoption）= **NOT STARTED**
- F6（Shared-memory Hallucination）= **NOT STARTED**

## 9. 结论
Stage 5.9-A′（F4→F1→F2→F3）实施与验证完成：deterministic 全绿、517 全绿、真实 DeepSeek A/B 均修复、
Naturalness 无显著回归。F5/F6 待用户单独批准后另行启动。

---

*归档于 2026-09-04。零代码修改、零 frozen 改动。*
