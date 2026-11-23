# 纠正跨会话召回：核查与设计说明

日期：2026-11-21 · 基于 main `48a7351` · 本页仅记录核查结论与最小方案

## 1. 问题假设

试用反馈是「每一次聊天他的纠正流程都会重新来一遍」。此前观测到：确认纠正后 `persona_memory.json` 的 `revision` 从 1 变 2，新值写进顶层 `corrections[]`；旧记忆被标为 `superseded`。

由此提出的根因假设是：`correction_longterm_projection.py` 没接入对话运行时，重启后检索不到新值。

## 2. 核查结果：当前 main 已接通

**这个假设在当前代码上不成立。** 按产品真实路径（`production_host.Host`，不是绕过 loader 的直接调用）实测：

1. `production_host.get_runtime()` 每次从 canonical 读取后调用 `load_runtime_persona(longterm, None)`（`stage6/host/production_host.py:166-172`）。
2. `load_runtime_persona()` 第 78 行调用 `phase2.project_active_corrections(longterm_persona_memory)`，把 active 的 memory-domain 纠正注入检索视图；会话 overlay 的覆盖关系再由 F5-e 归约后 omit（`runtime/persona_loader.py:64-108`）。
3. `PersonaRuntime.respond()` 对这份 base 做 `retrieve()` 和 `assemble()`（`runtime/persona_runtime.py:99-115`）。

真实输出（临时目录、`EX_REAL=0`）：

```
确认写回：revision=2，corrections=[('mi_9332c62deeded003', '话很多', 'active')]
重建 Host 后 preferences：旧项 superseded + 新项 mi_9332c62deeded003「话很多」active
重建 Host 后检索：'话很多'，score=1.0
追问输出：used.memory_items=['mi_9332c62deeded003']
组装上下文：system_text 含「话很多」= True
```

已有单元测试也覆盖 loader 投影：`runtime/tests/test_stage59_f5f_phase2.py`（Phase-2）与 `test_stage59_f5f_phase3b.py`（loader/归约）。

此前的失败观测是把 `persona_memory` 直接传给 `retrieve()`，绕过了 `persona_loader`，因此不能证明产品路径失效。

**也就是说：误判来自测试绕过了 `persona_loader`，产品真实路径已经接通。**


## 3. 方案（不再改功能）

建议把第 2 步从「先写会失败的测试」改为「先写一条**应该通过**的端到端回归测试」：

- 复现原流程：导入示例 → 纠正 → 确认写回 → 新建 Host/新会话 → 追问。
- 断言检索结果与组装上下文都含新值；同一路径在真机（本地模型）下再验一次。
- 测试放在 `runtime/tests/`（不改冻结 SHA 清单文件），提交信息可用 `test: regression for correction recall after restart`。

这样用测试锁定现状；若未来有人断开 loader 接线，测试会红。

## 4. 与 correction_conflicts 的关系

- 唯一语义权威仍是 `resolve_statements()`（`runtime/correction_conflicts.py:55`）。
- 同一 lane 多次纠正时，以 `resolve_statements` 的输出为准；持久化纠正与会话 overlay 一起归约，被覆盖者不再投影。不要在别处再做一次新旧比较。

## 5. 不做什么（范围边界）

- 不改冻结 SHA 清单中的文件（包括 `persona_loader.py`、`persona_runtime.py`、`correction_longterm_projection.py`）。
- 不改 `instance_persistence` 的写回/备份/锁；不新增第二套纠正存储。
- 不为了"修 bug"而改动当前已正确的行为。

## 6. 调查结论（试用者反馈的真实原因）

数据源：`stage6/cli/pilot_data/`（2026-09-05 真实试用，本地只读，未入库）。

**a) 会话记录怎么说**
- 用户只纠正过一次（"不对，他其实很话痨"），**确认并写回成功**：canonical `revision` 1→2、
  `corrections[]` 有 active 记录、旧记忆标 `superseded`、`versions/v1_20260905_*.json` 备份存在。
- 同一会话后续回复显示 persona **记得**这次纠正（"刚才不是你自己说我话痨的嘛"）。
- 问卷第 5 题「它记得你纠正过的吗？」回答 **y**。
- 但引导记录 `steps.chat` 显示 `corrections: 4, confirms: 4` —— 同一条纠正提议被**逐轮重复弹出**，
  用户按了 4 次 y，而 canonical 只有一次有效写入（revision 2、一份备份）。

**b) 时间线核对**
- `dev-history` 无逐日历史（已压缩为 2026-11-21 的 snapshot），无法直接比对 9 月 5 日的源码。
- `docs/internal/stage63_exit_review.md` §2.4：G3（2026-09-19，试用后 14 天）改动 8 个文件，
  其中 1 个 Host/CLI = `production_host.py`（其测试 23→73）。当前该文件里的
  `_existing_proposals()`（注释明言"否则每轮重复弹出"）与 `confirm_proposal` 的幂等
  （"重复 confirm 不重复写"）即为此问题而设。
- 跨会话召回本身**当时并没有坏**：`persona_loader` 的投影属 Stage 5.9-B，早于试用；
  G3 对 `instance_persistence`/`memory_retrieval` 的改动是生命周期（superseded/rejected 过滤），
  与召回接线无关。

**c) 重复弹窗的另一处来源（当前版本实测）**
- 纠正提议：**已不重复**。实测确认后 `pending_proposals` 归零、revision 稳定为 2。
- 新信息（new-fact）提议：**仍会重复**。`decide_memory_proposal()` 裁决后**不从**
  `session.pending_confirmations` 移除条目（`stage6/host/production_host.py:380-396`），
  `pending_memory_proposals()` 每轮全量返回（`:333-349`），`mvp_session._offer_memory_proposals`
  （`stage6/cli/mvp_session.py:119-129`）逐轮重新询问；拒绝只打印"已跳过"也不移除。
  实测：approve 之后提议仍在，下一轮继续弹。

**d) 结论**
- 试用者抱怨的真实原因是 **CLI 逐轮重复弹出确认提示**（当时是纠正提议重复；用户按 4 次 y），
  不是纠正结果丢失——问卷自己就回答了"记得"。
- 当前版本：**纠正提议的重复弹出已修复**；**新信息提议的重复弹出仍存在**（上面 c 的三处位置）。
  属实存缺陷，但按本任务约定（"如果还会出现，先汇报，不要修"）**不在本次修**，
  建议作为 v0.3.0 的独立条目另行立项：裁决后从 `pending_confirmations` 移除（或导出侧过滤已裁决项）。

## 7. 原"待确认"占位（已被上节取代）

- 试用者反馈的真实原因：已查明，见第 6 节。
