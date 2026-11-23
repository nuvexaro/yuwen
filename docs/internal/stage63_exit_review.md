# Stage 6.3 Exit Review / Closeout & Handoff

**文档状态**: NON-FROZEN 收口记录（Closeout / Handoff Record）。仅记录，不开发。
**本文件不属于 Frozen Runtime Baseline，不改变任何 Frozen / prior SHA / baseline。**

```
STAGE 6.3 = CLOSED / HANDOFF COMPLETE（Repo-side）
  Repo-side = COMPLETE
  External Clean-machine Verification = PENDING（属 External Acceptance Verification，非 Repo blocker）
  Frozen Core = G3 经用户批准改动 2 个 runtime 文件（其余 12 runtime / 5 schema / evaluation 未变，见 §2.4）
  P0 / blocker = none
  G3 = IMPLEMENTATION PASS / FINAL ACCEPTANCE PASS（2026-09-19）
       28/28 suites · 888 assertions · 0 failures · 0 skips

  ＞ 上方 Stage 6.3 收口快照为 2026-09-08 状态；G3 于 2026-09-19 收口，逐项见 §2.4 / §7。
```

> 本文件依据 **2026-09-08 源码取证 + 实测结果** 归档。内容以本仓库
> （仓库根目录）的源码、测试、文档、产物与实跑结果为准，
> 不依赖任何聊天记忆即可独立恢复 Stage 6.3 状态。

---

## 1. 最终判定

| 维度 | 判定 |
|---|---|
| **Repo-side Stage 6.3** | **COMPLETE**（实现 / 打包 / 自检 / 测试 / 边界全部闭合，见 §2）|
| **External Clean-machine Verification** | **PENDING**（见 §4）|
| **PENDING 是否构成 Repo blocker** | **否**。原因：Clean-machine 复验的执行前提（一台不属于本机、无 Python、有真人 + 真 DeepSeek key 的普通 Windows 机器）**在仓库边界内永远无法满足**；它是一次**外部验收测试**，而非可自动化 / 可复现的 Repo 实现门。Repo 侧能自证的全部（构建、打包、自检、schema、frozen SHA、测试套件）均已在 §2 实测通过。 |

**收口口径**：Repo 侧可正式宣告 **COMPLETE**。若要把 "Productization COMPLETE" 严格定义为"含真实干净机跑通"，则表述为 **CONDITIONAL COMPLETE（pending external verification）**。本文档采用后者更稳的表述，但**不影响**"Repo 无 blocker、可进入下一阶段"这一事实。

---

## 2. Stage 6.3 完整验收证据

### 2.1 EXE / ZIP 产物（2026-09-05 构建，2026-09-08 复核）
| 产物 | 路径 | SHA-1 |
|---|---|---|
| 分发 ZIP | `dist_pkg/ex-ai-pilot.zip` | `c01bbc83275037de498a307dad9179bc2158dab3` |
| 可执行文件 | `dist_pkg/dist/ex-ai-pilot/ex-ai-pilot.exe` | `2570828d568f195673a0fb25abbc420a02fbf0b5` |
| 内置示例（dist 根） | `dist_pkg/dist/ex-ai-pilot/sample_messages.json` | `6c003e54483f976442d8e81dd397de8ad18d1b95` |
| 内置示例（_internal） | `dist_pkg/dist/ex-ai-pilot/_internal/messages.json` | `6c003e54483f976442d8e81dd397de8ad18d1b95` |

> 注：`_internal/messages.json`（spec 打入）与 dist 根 `sample_messages.json`（build.bat 拷贝）
> **内容哈希相同**，双冗余实证成立；exe 为 PE32+ Windows console x86-64 真实文件（14,231,818 B）。

- 分发的 5 个 schema 均复制到 dist 根（配合模块 `__file__` 相对加载）：`persona_memory` / `message` / `evidence_candidate` / `merge_group` / `resolved_evidence_bundle`。

### 2.2 `--selftest` 实测（2026-09-08，临时 `EX_DATA_ROOT`，非破坏性）
实跑 `dist_pkg/dist/ex-ai-pilot/ex-ai-pilot.exe --selftest` → exit 0：
```json
{"data_root_ok": true, "schemas": {"pm": true, "bundle": true, "evidence": true, "merge": true, "message": true},
 "jsonschema": true, "openai": true, "create_ex_under_userdata": true, "import_chain": true}
```
覆盖：data_root / 5 schema 加载 / jsonschema / openai 依赖 / create-ex 落用户数据区 / import 链（5.2–5.5）。
**不覆盖**："真无 Python 机器 + 无预置 key 时双击启动 / 输 key / 真实多轮对话" 的人工路径（见 §4）。

### 2.3 测试套件（2026-09-08 实跑，全绿）
**27/27 套件全部 exit 0、零失败、零跳过。**

- 9 基线套件 = **519/519**：
  chat_parsers 83 / import_pipeline 54 / evidence_extractor 57 / evidence_merge 63 / resolve_bundle 59 /
  persona_memory_builder 74 / eval_framework 33 / runtime **56** / benchmark_harness 40。
  （历史记录称 517；现 runtime 套件含后加测试为 **56**，故基线为 **519**。无失败。）
- 阶段套件全绿：stage59_f1(16) / f2f3(26) / f4(15) / f5(16) / f5d(18) / f5d_d3(17) / f5e(17) / f5f(19) /
  f5f_phase2(16) / f5f_phase3b(14) / f5b_reopen(12) / f4_instance(8)
- Distribution Wrapper：skill_writer_v12(19) / version_manager_v12(12) / instance_persistence(12)
- Stage 6.1 / 6.3：gateway_fallback(6) / test_production_host(23) / test_mvp_cli(11)

### 2.4 Frozen / prior SHA（2026-09-08 实测；2026-09-18 边界同步；2026-09-19 G3 更新）

> **2026-09-19 G3 Memory Item Lifecycle（经用户批准实施）**：
> 修改 2 个 Frozen 文件 —— `runtime/instance_persistence.py`（新增 `apply_memory_lifecycle()` 纯内存
> create/decide；`write_back()` 增 `lifecycle_ops` 可选参数，既有 correction 写语义不变）、
> `runtime/memory_retrieval.py`（新增 `_NON_CURRENT_STATUSES = {superseded, rejected}`；`retrieve()`
> 两处 selection filtering；`default_scorer()` 零修改）。
> 其余 12 个 Frozen runtime、5 个 schema、`evaluation/*`、`benchmark/*` 均未改动。
> 仅上列 2 行 SHA 更新；未新增第二套 SHA source。
> **收口结论（2026-09-19 实跑）**：G3 Implementation = **PASS**；G3 Final Acceptance = **PASS**。
> 全量 **28/28 套件 · 888 assertions · 0 failures · 0 skips**（较 §2.3 的 27 套件新增
> `real_llm_adapter_config`；runtime 56→64、instance_persistence 12→35、production_host 23→73，
> 增量即 G3 新增测试，无套件回退）。本轮改动文件 **8 个**（2 frozen runtime + 2 frozen 台账 +
> 3 测试 + 1 Host/CLI），20 项 SHA 与本节逐一比对零漂移。
>
> **G3 语义边界（只读核对通过，记录备查）**：
> pending_confirmation 的 conflict-safety 语义保持（`memory_retrieval.py:18` 明确将其**排除**在
> `_NON_CURRENT_STATUSES` 之外，仍可召回）；rejected retrieval filtering 生效（主候选 +
> conflict-sibling 两条路径）；create 的 fallback bucket 闸门为 **fail-closed**（置于
> `_apply_create` 唯一写入 choke point，无关键词通向 `shared_experiences` 兜底值）；
> rejected **不可**被普通 create 复活，仅经显式 `revive_rejected_item()`；
> `correction_conflicts.resolve_statements` 仍是 correction 语义唯一 authority（G3 未复制该语义）；
> `default_scorer()` 零修改。

> **2026-09-18 冻结边界同步（经用户裁定）**：
> `runtime/llm_gateway.py`、`runtime/memory_proposal.py` 正式纳入 Frozen Core runtime（共 14 个）；
> `runtime/instance_persistence.py` 维持 Frozen Core，并据此修正本文档 §3 中与之冲突的 Non-Frozen 归类；
> `runtime/mock_responders.py` 单列为 Testing / Benchmark Support（不属于 Product Frozen Core）。
> 本同步**未重新生成或改变任何 SHA**，仅记录既有值并修正分类语义。

> **2026-11-23 v0.3.0 编造防护（经用户批准 reopen，两阶段）**：
> 阶段一改 `runtime/reality_boundary.py`（「共同过去 / 个人事实」结构识别 + 强化 `boundary_guard`）；
> 阶段二改 `runtime/persona_runtime.py`（护栏补「带前提」条款 + 出口事后检查 `_untraceable_narrative`）。
> 其余 12 个 runtime、5 个 schema 未变。下表 2 行 SHA 已更新。
> 原因与验收数据见 `docs/design/no-fabrication.md`、`benchmark/fabrication_probe/after_summary.md`。

**Frozen Core（runtime，14 个）**：
```
runtime/persona_runtime.py            c4b1b14c560f   (v0.3.0 no-fabrication reopen 后)
runtime/reality_boundary.py           d6399b5e77ef   (v0.3.0 no-fabrication reopen 后)
runtime/persona_constraints.py        c90a342a0a2f
runtime/context_assembly.py           fc72bd181019
runtime/session_store.py              26ffbc7432a2
runtime/correction_runtime.py         6e95bd2316be
runtime/correction_conflicts.py       a69c5b66e6ce
runtime/correction_export.py          30d0921fbbaa
runtime/correction_longterm_projection.py 59cdc89f1b03
runtime/persona_loader.py             001733dd7ca4
runtime/memory_retrieval.py           58b3a2d977bf   (G3-4 selection filtering 后)
runtime/instance_persistence.py       08a165617f57   (G3-1/G3-3 lifecycle 后)
runtime/llm_gateway.py                1bbeeb9f27ea
runtime/memory_proposal.py            14df24c3c8f3
```
**Testing / Benchmark Support（不属于 Product Frozen Core；受 benchmark 可复现性保护）**：
```
runtime/mock_responders.py            84e0b6345980
```
> 依据：文件自述「确定性 mock responder（供 gateway 注入，5.6/测试用）…只为测试/评测，不是产品回复质量目标」；
> 当前调用方仅 `benchmark/benchmark_harness.py` 与 `runtime/tests/test_runtime.py`，**无产品运行路径调用**。
> **不得**将其误标为 Non-Frozen Product Layer。

**Frozen Core（evaluation）**：
```
evaluation/eval_runner.py             66783585733c
```
**Historical / prior baseline（SHA 台账留痕；不属于当前 Frozen Core）**：
```
tools/skill_writer_v12.py             9069bc22ed78
tools/version_manager.py              d2fd131943d7
```
> 二者在 §3 边界表中为 **Non-Frozen Product Layer**；此处 SHA 仅为历史 baseline 记录，
> 不得据此解释为当前 Frozen Core。
**不可变 schema**（SHA 基线，见 stage58_exit_review §6 / stage59 系列记录，未漂移）：
`persona_memory.schema.json 27750ee4ace4`、`message.schema.json f0224e7a9697`、
`evidence_candidate.schema.json b679d69af1d0`、`merge_group.schema.json aec7f85c0780`、
`resolved_evidence_bundle.schema.json b497d601bd75`。

### 2.5 Packaging 修复（Clean-machine Import 缺陷，已闭环）
- 修复内容：pilot_recorder 的 option-A sample 原走 `_HERE/../../evaluation/...`（打包后 `_HERE` = `_internal` → 追到 dev 路径）。
- 修复：`packaging/ex_ai_pilot.spec` 将示例正式打进 `_internal/`（原文件名 `messages.json`）；
  `stage6/cli/userdata.py` 加 `resolve_sample_path()`（候选链：`EX_SAMPLE_IMPORT` → `_MEIPASS`(sample+messages) →
  EXE 目录(sample+messages) → cwd → `.ex_ai` → dev 仓库路径兜底）。
- 决定性验证（已有记录）：隐藏 dist 根 sample 后 EXE selftest 仍 exit 0（纯靠 `_internal/messages.json`，无 dev-path）。
- Packaging 文件 SHA：
```
packaging/ex_ai_pilot.spec            36f39508158c
packaging/build.bat                   46436ec1d34f
packaging/README_PACKAGING.md         ead0351294d4
packaging/CLEANMACHINE_CHECKLIST.md   8ec0e6a24a0b
```

### 2.6 userdata / key 安全边界
- 用户运行时数据写 `%USERPROFILE%\.ex_ai\`（`stage6/cli/userdata.py`；`EX_DATA_ROOT` 可覆盖，开发/测试用）。
  结构：`.ex_ai\exes\{slug}\persona_memory.json`、`.ex_ai\sessions\`、`.ex_ai\pilot_data\`。
- 不写 PyInstaller bundle / `_MEIPASS` / `_internal`；不依赖 EXE 所在目录可写。
- **API Key 安全（保持原设计）**：用户输入自己的 key，`getpass` 不回显；key 仅存当前进程内存；
  不写 `.env` / config / pilot_data / 日志；不打包任何 key；退出即消失；已设 `DEEPSEEK_API` / `OPENAI_API_KEY` 环境变量者不重复询问。
- CLI 层 SHA：`start.py d808e3ef94dc`、`userdata.py d575adeca245`、`mvp_cli.py e4c11fe0245e`、
  `mvp_session.py 453dbda2d162`、`privacy.py a7c0eb1f11d0`、`pilot_recorder.py 99a2edc32616`、`test_mvp_cli.py f639e6b53068`。

### 2.7 已知 non-blocking limitations（记录，不修）
见 §5。

---

## 3. 边界区分

| 层 | 内容 | 状态 |
|---|---|---|
| **Frozen Core** | 5 个 schema（v1.2 / v1.0）+ runtime 冻结核 **14 个**（SHA 与清单见 §2.4）+ evaluation（eval_runner）+ 5.2–5.5 tools | 全 FROZEN，未改动；本次收口零触碰 |
| **Testing / Benchmark Support** | `runtime/mock_responders.py`（SHA 见 §2.4） | 仅供测试/评测；受 benchmark 可复现性保护，**不属于 Product Frozen Core**，也**不是** Non-Frozen Product Layer（2026-09-18 裁定） |
| **Non-Frozen Product Layer** | `stage6/host/production_host.py`（09d9d82da1f0）、`stage6/cli/*`、`packaging/*`、`dist_pkg/*`、`tools/skill_writer_v12.py`、`tools/version_manager.py` | 本层为实现/交付载体；本次收口仅新增本文档 |
| **External Delivery / Pilot Boundary** | 真实用户 Pilot、Clean-machine 复验、Production Host 部署、real-user trial、telemetry、生产配置 | 仓库边界之外；不在此 Repo 内建 fake host / 不冒充 wiring |

边界铁律：persona_memory v1.2 = 唯一长期事实源；PersonaRuntime = 唯一运行核心；persona_loader = 装载边界；
SKILL.md / 分发壳零人格事实；Production Host = External。禁止第二套人格/记忆事实源；禁止静态 Markdown 绕过 PersonaRuntime。

---

## 4. Clean-machine / Real-user Pilot

### 4.1 当前状态
- **PENDING**（外部验收未执行）。执行入口与脚本已全部就绪：
  `packaging/CLEANMACHINE_CHECKLIST.md`（A–G 步骤 + PASS/FAIL 判据）、`stage6/cli/PILOT_README.md`、
  `stage6/cli/pilot_recorder.py`（问卷/记录）、`dist_pkg/ex-ai-pilot.zip`。

### 4.2 缺失证据
1. 一台**真·无 Python、无本项目依赖**的普通 Windows 机器（Win10/11）上的双击启动/全流程跑通。
   - 本开发机 **不能充当**：装了 Python 3.14.4 且 `DEEPSEEK_API` 已 SET（EXE 会跳过 key 输入提示），无法验证 "无预置 key → 提示输入自己 key（不回显）" 路径。
2. 一个**真实测试者 + 其本人的 DeepSeek key** 走完：Create → Import(示例 A) → Chat → Correction → Confirm → 退出 → 重开验证记忆。
3. 回填：`CLEANMACHINE_CHECKLIST.md` 结果 或 `pilot_data` 里对应代号 .json（不含 key / 原始聊天）。

### 4.3 验收步骤
按 `packaging/CLEANMACHINE_CHECKLIST.md` A–G：
A 确认无 Python → B 解压 ZIP（见 exe + `_internal`）→ C 双击启动、输 key 不回显 →
D 走完 Pilot 流程（Create/Import/Chat/Correction/Confirm/quit）→ E 重新打开验证记忆 →
F 回填 11 题 → G（可选）检查 `.ex_ai\` 落盘且 key 未落盘。
**PASS**：能启动 → 输 key → Create → Import → Chat → Correction → Confirm → 退出 → 数据落 `.ex_ai\`；
重开能回旧 Ex 且记得纠正（若引导不支持"回旧 Ex"，此项记现象不判 FAIL）。
**FAIL**：双击闪退 / 无法输 key / Create·Import 报错 / `.ex_ai` 未生成 / key 落盘出现。

### 4.4 定性
**Clean-machine / Real-user Pilot 属 External Acceptance Verification，不是 Repo Implementation Gate。**
它应在"Repo 收口"之后作为**外部交付第一步**触发，同时补上 §4.2 证据缺口。

---

## 5. 已知但不阻塞的事项（记录，不升级，不因收口改代码）

| # | 事项 | 性质 | 归属 |
|---|---|---|---|
| 1 | **Clean-machine verification PENDING** | External Acceptance，非 Repo blocker | §4 |
| 2 | **"重新打开 EXE 后回到旧 Ex"目前不够直观** | 现有 Pilot 引导每次新建 Ex；checklist F.8 明示记录现象即可，不判 FAIL | 交互缺口（未来小改候选，需单独批准）|
| 3 | **gateway_fallback** | runtime 已通过 `error:"gateway_fallback"` 暴露失败信号（Stage 6.1 reopen 产物）；Pilot 引导如何呈现给真人待外部验证 | 已记录边界 |
| 4 | 孤立"她" referent resolution | `runtime/known_limits.md` F5-d Known Limit；仓库内不修，属未来独立能力 | 已记录边界 |
| 5 | 投影 memory_item_id ≠ 持久化 correction id | `docs/internal/stage59_e2e_milestone.md` Known Limit；content/correction_id 关联正确，不作为 defect | 已记录边界 |
| 6 | persona claim 无独立 status/supersede 等 schema 结构限制（P1-B/P1-C/P2-A） | `evaluation/known_schema_limits.md`；Future v1.3 | 已记录边界 |

> 铁律：**不把以上任何一项擅自升级成 blocker；不为收口修改 frozen 源码 / runtime / schema；不为收口 re-baseline。**

---

## 6. 完整产物 / 测试 / SHA / 验证清单（独立恢复用）

本文件 + 下列路径即可不依赖聊天记忆完整恢复 Stage 6.3：

- **本文件**：`docs/internal/stage63_exit_review.md`
- **Pilot / Clean-machine 指南**：`packaging/CLEANMACHINE_CHECKLIST.md`、`stage6/cli/PILOT_README.md`、`packaging/README_PACKAGING.md`
- **打包**：`packaging/ex_ai_pilot.spec`、`packaging/build.bat`
- **分发产物**：`dist_pkg/ex-ai-pilot.zip`（SHA `c01bbc83275037de…`）
- **EXE 目录**：`dist_pkg/dist/ex-ai-pilot/`（含 exe、5 schema、`sample_messages.json`、`_internal/messages.json`）
- **构建日志**：`dist_pkg_build.log`（PyInstaller 6.21 / Python 3.14.4 / Windows-11-26200）
- **CLI 源码**：`stage6/cli/`（start / userdata / mvp_cli / mvp_session / privacy / pilot_recorder / test_mvp_cli）
- **Host 源码**：`stage6/host/production_host.py`、`stage6/host/test_production_host.py`
- **CLI e2e 结果**：`stage6/cli/e2e_out/e2e_stage.json`、`e2e_final.json`
- **Stage 6.1 e2e 结果**：`stage6/host/e2e_results/stage61_e2e_847483db38.json`(+`_full`)
- **测试套件**：见 §2.3 列出的 27 个测试文件路径
- **SHA 全集**：见 §2.4–§2.6
- **运行时复现实测命令**：
  - 9 基线：见 `memory/ex-skill-stage-state.md` 记录的命令（`python`、`PYTHONIOENCODING=utf-8`）
  - EXE 自检：`ex-ai-pilot.exe --selftest`（用临时 `EX_DATA_ROOT` 可非破坏复验）
  - 真实 LLM 校验脚本（需 `DEEPSEEK_API`，非本收口必须）：`benchmark/stage59_a_validate.py` 等

---

## 7. Handoff

```
STAGE 6.3 = CLOSED / HANDOFF COMPLETE（Repo-side）
  Repo-side = COMPLETE（§2 全证据闭合）
  External Clean-machine Verification = PENDING（§4，External Acceptance，非 Repo blocker）
  Frozen Core = G3 经批准改动 2 个 runtime（见 §2.4）
  P0 / blocker = none
  G3 = CLOSED（IMPLEMENTATION PASS / FINAL ACCEPTANCE PASS，2026-09-19）
```

1. **Stage 6.3 已收口**。Repo 侧实现、打包、自检、测试、边界全部闭合；唯一剩余为外部 Clean-machine 复验。
2. **Clean-machine / Real-user Pilot 是下一步外部验证**：按 `packaging/CLEANMACHINE_CHECKLIST.md` 在真·无 Python 机器上执行，交回清单 / `pilot_data` json。
3. ~~**若继续进行仓库内工程开发，下一候选为 G3 Memory Lifecycle**（P1，多次 deferred 的唯一 in-repo 候选）。~~
   → **状态更新（2026-09-19）**：G3 已完成并收口（Implementation PASS / Final Acceptance PASS）。
   本条为 Stage 6.3 归档时的历史候选记录，保留备查，不再作为待办。
4. ~~**G3 必须先经过独立 Architecture / Design Review**，经用户批准后才可进入实现；G3 触及 frozen runtime/schema（P1-B 级），需明确授权与 re-baseline 判定。~~
   → **状态更新（2026-09-19）**：该前置条件已在 G3 实施前满足 —— 经独立 Architecture / Design
   Review 并由用户明确批准，仅改动 2 个 frozen runtime 文件（见 §2.4），未改 schema。
   **本条作为"frozen 改动的前置纪律"继续有效**：任何后续触及 Frozen Core 的改动仍须先过
   独立 Review + 用户批准。
5. **未经批准不得修改 frozen core**（schema / runtime 冻结核 / eval / 5.2–5.5 tools）。
   本收口（2026-09-08 归档时）严格遵守：零 frozen 改动、零 runtime/schema 改动、零真实 LLM API 消耗。
   （G3 为 2026-09-19 的**独立、经批准**改动，不属于本收口范围，见 §2.4。）

---

*记录于 2026-09-08。Stage 6.3 Exit Review / Closeout & Handoff；仅新增本文档，零代码、零 Frozen 改动、零 real-LLM 调用。*
