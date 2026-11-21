# CLAUDE.md — 前任.skill 项目约束（Agent 入口）

> 本文件只回答一件事：**开始改代码前，哪些东西不能随便动。**
> 行为纪律（阶段门禁 / 报告格式 / 中文沟通 / Python 环境 / ID 规则等）见 memory，不在此重复。

## 1. Frozen Core

**唯一权威清单：`docs/internal/stage63_exit_review.md` §2.4**（含实测 SHA）。本文件不复制 SHA 值，避免出现第二套事实源。

该清单包括：

- **5 个 frozen schema**：`persona_memory.schema.json`、`message.schema.json`、`evidence_candidate.schema.json`、`merge_group.schema.json`、`resolved_evidence_bundle.schema.json`
- **14 个 frozen runtime 文件**（均在 `runtime/`）：`persona_runtime.py`、`reality_boundary.py`、`persona_constraints.py`、`context_assembly.py`、`session_store.py`、`correction_runtime.py`、`correction_conflicts.py`、`correction_export.py`、`correction_longterm_projection.py`、`persona_loader.py`、`memory_retrieval.py`、`instance_persistence.py`、`llm_gateway.py`、`memory_proposal.py`
- **frozen evaluation**：`evaluation/eval_runner.py`

**规则**：修改任何 Frozen Core 文件前，必须先向用户报告并获得批准。获批准后才允许实施；实施后必须同步维护冻结台账与 SHA baseline。

SHA baseline 当前分散在 3 处，改动 frozen 后需一并核对：

- `evaluation/eval_runner.py:33`
- `benchmark/benchmark_harness.py:35`
- `benchmark/targeted_retest.py:111`

## 2. Testing / Benchmark Support

`runtime/mock_responders.py` **不属于 Product Frozen Core**（文件自述「只为测试/评测」；调用方仅 `benchmark/benchmark_harness.py` 与 `runtime/tests/test_runtime.py`，无产品运行路径）。

它受 **benchmark 可复现性保护**，仍保留在两条 benchmark 保护列表中，**不得**因分类调整而移除；也**不得**被误标为 Non-Frozen Product Layer。

## 3. Non-Frozen Product Layer

以下文件属实现/交付载体，可按产品层流程演进：`stage6/host/production_host.py`、`stage6/cli/*`、`packaging/*`、`dist_pkg/*`、`tools/skill_writer_v12.py`、`tools/version_manager.py`。

> 注：`tools/skill_writer_v12.py` 与 `tools/version_manager.py` 在 `docs/internal/stage63_exit_review.md` §2.4 中留有 SHA，但那只是 **historical / prior baseline 留痕**，**不属于当前 Frozen Core**。

## 4. 不可为"减少代码"而删除的保护

`runtime/instance_persistence.py` **属于 Frozen Core**，其数据安全机制属于必要保护，**不得因 Ponytail 最小实现原则或任何"减少代码"的理由删除、弱化或绕过**：

- lock registry（单 Ex 写者锁）
- version backup（写前版本快照）
- temp + `os.replace` 原子写入
- 写入前结构校验

**测试与验收必须实际运行。** 不得把历史报告中的"通过"当作当前运行通过的证据。

## 5. 已声明产品 / 架构边界

- **`correction_conflicts.resolve_statements` 是 correction 语义的唯一 authority**，不得建立第二套 correction 语义源。
- **G3 Memory Lifecycle** 在实现前必须经过独立 Architecture / Design Review，并获得用户批准。
- **`runtime/known_limits.md` 与 `evaluation/known_schema_limits.md`** 已声明的产品边界，不得直接当作缺陷绕过并实现。
- **不得建立第二套 Persona / Memory 事实源**；不得通过静态 Markdown 绕过既有 PersonaRuntime 架构。

## 6. 与 Ponytail 的关系

Ponytail 的"最小实现"原则**不覆盖**本文件约束：

- 最小改动 ≠ 可以删除必要机制（§4）
- 最短 diff ≠ 可以突破项目架构边界（§5）
- 不改 Frozen Core，除非获用户批准（§1）
