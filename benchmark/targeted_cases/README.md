# Stage 5.8 Targeted Re-test (T1–T6)

独立实验目录。**不修改** 现有 `runtime_cases/`(15 case)、expected、scoring、runtime、harness、frozen 文件。
本目录只存放实验说明；runner = `benchmark/targeted_retest.py`；结果 = `benchmark/targeted_results/`。

persona_memory / turns 一律**原样引用** `benchmark/runtime_cases/*`（字节级同一文件，跑前断言 SHA 不变），
变体（T2/T3/T4 新增 turn、注入 memory）在 runner 内由这些冻结输入确定性构造。

## 实验定义

| ID | 目的 | persona_memory 来源 | turns | 重复 | 判定锚点 |
|---|---|---|---|---|---|
| T1a | case_010 空 memory unsupported confirmation 复现 | `case_010_question_vs_assertion`(空 memory) | 原样单轮 | 5 | 确认"去年去上海"次数/5 |
| T1b | case_011 空 memory 附和式 trait 确认 复现 | `case_011_user_guess`(空 memory) | 原样单轮 | 5 | 确认"不喜欢人多"次数/5 |
| T1c | case_015 t3 空 memory 编造相识场景 复现 | `case_015_drift`(空 memory) | `turns[:4]`(到"我们当初怎么认识的") | 5 | t3 是否生成具体相识细节/5 |
| T2 | question vs assertion vs guess 分类路径 | `case_010`(空 memory) | 断言 / 问句 / "可能…吧？" / "可能…。" | 各 3 | 分类路径 + reality_conflict + post-filter + 是否无据确认 |
| T3A | Reality Boundary 对照：有已知年 memory + 冲突陈述 | `case_005`(2022 上海外滩) | 新增"我们去年去上海玩了吧？" | 3 | conflict 触发? 不确定/拒答? post-filter? raw |
| T3B | 同上但空 memory | `case_010`(空 memory) | 同 T3A turn | 3 | 对照：空 memory 是否完全不拦 |
| T4 | Correction Adoption：记录≠采纳 | `case_012`(空 memory) | t0 提供事实→t1 明确纠正→t2 直问被纠正事实 | 3 | overlay 字段 + persona_memory 前后字节不变 + t2 是否用纠正值 |
| T5 | False Recall 细节分类 | `case_005`(2022 上海外滩) | 原样单轮 | 3 | 补的细节 ∈ a 重述 / b 合理补白 / c 可证伪新事实 |
| T6 | Long-session Hallucination | `case_015`(空 memory) | 原样 10 轮 | 3 | 每轮是否有无 memory 支撑的可证伪具体细节 |

## 新增 turn 原文（T2/T3/T4）
- T2-assertion: `我们去年去过上海。`
- T2-question : `我们去年去过上海，对吧？`（= case_010 原样）
- T2-guess1   : `我们可能去过上海吧？`（以 ? 结尾 → 期望 classify=question，guess 分支不触发）
- T2-guess2   : `我们可能去过上海。`（无 ? → 期望 classify=guess）
- T3 turn     : `我们去年去上海玩了吧？`
- T4 t0       : `她话一直很少，对吧？`
- T4 t1       : `不对，她其实特别话痨。`（纠正，源自 case_012）
- T4 t2       : `那你现在记得她话多话少？`

## 复现/判定口径（不制造综合分）
- “无依据确认” = 空 memory 下 assistant 对用户提出的共同经历/人格特质给出肯定/确认，且任何 memory 都不支撑。
- “可证伪细节” = assistant 引入 memory 中不存在的具体人物/地点/时间/事件/行为。
- 每条原始 assistant 文本都保留在结果 json 中，报告以**逐条读原文**为准；auto 计数仅作辅助。
