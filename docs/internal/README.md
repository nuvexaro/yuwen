# docs/internal — 开发期阶段记录

本目录是**开发期的内部阶段记录**，不是给使用者读的文档。
正式的使用说明请回到仓库根的 `README.md` / `INSTALL.md`，数据流向见 `docs/COMPLIANCE.md`。

## 里面的文件是什么

| 文件 | 内容 |
|---|---|
| `stage58_exit_review.md` | Stage 5.8 收口评审（boundary 触发面 F1–F6 的问题与结论） |
| `stage59_a_finalization.md` | Stage 5.9-A′ 实施与验证结果存档 |
| `stage59_e2e_milestone.md` | Stage 5.9 真实 E2E 里程碑与已知限制（含 projection id Known Limit） |
| `stage59_handoff.md` | Stage 5.9 正式冻结/交接记录（含 Remaining Backlog） |
| `stage63_exit_review.md` | Stage 6.3 收口与交接（Frozen Core 权威清单 §2.4、Pilot 与 Clean-machine 状态、后续候选） |

## 阅读须知

- 这些文档记录的是**当时的判断**，包含内部代号（F5-c、L2-B1、G3、D3…）、实测 SHA 值与阶段门禁结论。
- 文档里出现的绝对路径、SHA、测试计数都属**历史留痕**，不保证与当前代码一致；以代码和 `run_tests.py` 的实际结果为准。
- 部分结论已被后续阶段推翻或完成（例如 G3 在 2026-09-19 已完成，但文档里仍保留"未开始"的旧记录）。这类地方文档内通常已加「状态更新」标注。

## 与 benchmark/ 的关系

`benchmark/stage59_*` 下的脚本与结果目录是同一批阶段工作的**可执行证据**，因涉及 import 路径与测试引用，
**没有随本文档一起移动**，仍保留在 `benchmark/` 原位置。请不要因为文档搬走就以为脚本也失效了。
