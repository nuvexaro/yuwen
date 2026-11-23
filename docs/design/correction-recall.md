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

## 6. 待确认

- 试用者反馈的真实原因：见第 3 步的调查结果（调查完再回填到这一节）。
