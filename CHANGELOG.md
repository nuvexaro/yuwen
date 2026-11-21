# 相对上游 therealXiaomanChu/ex-skill 的改动

本仓库基于 [therealXiaomanChu/ex-skill](https://github.com/therealXiaomanChu/ex-skill) 修改。

上游提供的是「在 Claude Code 里生成前任 Skill」的提示词 + 几个轻量 Python 工具；
本仓库在此基础上重做为**可本地运行、可测试、可打包成 Windows 程序**的实现。
下面只写「做了什么」，不评价效果。历史阶段记录见 `docs/internal/`。

---

## 版本

### 未发布（v0.2.0）

- 新增**本地模型后端**：`YUWEN_BACKEND=local` 时改用本机 Ollama（OpenAI 兼容接口），不需要 API key，数据不出本机；默认仍是 `deepseek`，两种后端并存
- 本地模式复用已有变量（`OPENAI_BASE_URL` / `EX_MODEL` / `OPENAI_API_KEY`），一律 `setdefault`，**不覆盖用户手动设置**；换模型只需 `EX_MODEL=yuwen-4b-q8`
- `start.py` 增加后端选择菜单（`--backend` / `YUWEN_BACKEND` / 交互三种方式），选本地时检查 Ollama 服务与模型是否存在；不满足时打印安装与拉取步骤并正常退出（退出码 3，不崩溃）
- 网关新增 `<think>…</think>` 剥离，作为「关不掉思考模式」的兜底；本地模式下同时尝试用 `chat_template_kwargs.enable_thinking=false` 从接口层关闭
- 新增 `runtime/tests/test_local_backend.py`（36 断言）：后端选择、setdefault 语义、local 不要求 key、去 think、Ollama 健康检查；全部用假 SDK / 假 urllib，不依赖真实 Ollama，CI 可跑
- README / README_EN 新增「使用本地模型」章节（硬件建议、步骤、限制）；COMPLIANCE 新增 5.1 节说明本地模式的数据流向

### v0.1.1（2026-11-21）

- 新增 **Windows 安装程序**（Inno Setup，`packaging/installer.iss`）：当前用户安装、无需管理员权限、默认装到 `%LOCALAPPDATA%\Programs\yuwen`、开始菜单快捷方式 + 可选桌面快捷方式、简体中文 / 英文界面、带卸载程序并出现在「设置 → 应用」里；**卸载不删除用户数据**，卸载完成时会提示数据位置与手动删除方法
- 随仓库附带简体中文语言文件 `packaging/languages/ChineseSimplified.isl`（来自 Inno Setup 官方 Unofficial 翻译），构建时无需联网
- README 补充：下载入口与状态徽章、**Windows SmartScreen 安全提示**（含 SHA256 校验命令）、**获取 DeepSeek API Key**、**怎么准备聊天记录**、**卸载与删除数据**
- README 新增**架构图**（mermaid，中英双语），画出导入链 / 对话链 / 纠正分支
- 无功能代码改动；`run_tests.py` 28/28 通过

### v0.1.0（2026-11-21）

首个公开版本，内容即下面「数据合同」起至「2026-11-21 发布前修复」的全部改动。

---

## 数据合同（JSON Schema）

- 新增 `persona_memory.schema.json`（v1.2）：人格 5 层（L0–L4）+ 记忆 9 类 + `corrections[]`，作为每个 Ex 的唯一长期事实源
- 新增 `message.schema.json`：统一的 ChatImport 结构，微信与 QQ 共用同一份消息模型
- 新增 `evidence_candidate.schema.json`、`merge_group.schema.json`、`resolved_evidence_bundle.schema.json`：证据抽取 → 合并 → 解析三段的数据合同
- 上述 5 个 schema 被冻结，并由测试按 SHA-1 校验（见 `evaluation/eval_runner.py` 的 `FROZEN`）

## 导入管线（`tools/`）

- 重写 `wechat_parser.py`：只支持 `wechatmsg_txt` / `liuhen_json` / `auto`，明确不支持 csv / html / sqlite（上游文档曾声称支持）
- 重写 `qq_parser.py`：支持 txt 与 `.mht/.mhtml`
- 新增 `chat_parser_common.py`：统一 ID、指纹、去重、参与者判定、编码处理
- 新增 `evidence_extractor.py` → `evidence_merge.py` → `resolve_bundle.py`：证据抽取、跨导入合并、bundle 解析
- 新增 `persona_memory_builder.py`：把证据解释为 Persona + Memory，程序侧掌控 provenance / ID / lifecycle / 去重 / 冲突 / 置信度上限
- 新增 `import_pipeline.py`：把上面的步骤串成一条命令
- 新增 `skill_writer_v12.py`、`version_manager.py`：生成 v1.2 实例目录、版本备份与回滚

## 对话运行时（`runtime/`）

- 新增 `persona_runtime.py`：加载 persona_memory → 组装上下文 → 调用 gateway → 产出回复
- 新增 `persona_constraints.py`、`context_assembly.py`：把 L0–L4 渲染成系统块，按 token 预算裁剪，禁止全量塞入人格
- 新增 `reality_boundary.py`：时间类事实冲突检测（非时间类未覆盖）
- 新增 `memory_retrieval.py`：规则检索（term overlap + valid_period），无向量
- 新增 `session_store.py`：会话持久化（每轮整存）
- 新增 `llm_gateway.py`：供应商无关的调用层（mock / adapter / 超时 / 重试）
- 新增 `persona_loader.py`：装载与投影（含 correction 的长期投影）

## 纠正闭环

- 新增 `correction_runtime.py`：会话级纠正 overlay
- 新增 `correction_conflicts.py`：`resolve_statements()` 作为纠正语义的唯一权威
- 新增 `correction_export.py`：把已确立的纠正导出为 proposal
- 新增 `correction_longterm_projection.py`：把纠正投影进长期记忆视图
- 新增 `instance_persistence.py`：确认后的纠正原子写回 `persona_memory.json`（写前备份、schema 校验、单 Ex 写者锁）

## 评测（`benchmark/`、`evaluation/`）

- 新增 `evaluation/`：14 个 golden case 的数据集、AUTO 断言（schema / provenance / determinism / negative / conflict / temporal）、semantic 标注与报告聚合
- 新增 `benchmark/`：runtime 用例集（15 个）、mock/真实 adapter 的 harness、结果记录格式
- 新增针对各阶段的回归测试（`runtime/tests/`、`tools/test_*.py` 等），共 28 个测试套件

## Pilot CLI 与打包（`stage6/`、`packaging/`）

- 新增 `stage6/cli/`：`start.py`（一次性引导）、`mvp_cli.py`（create/import/chat/delete）、`mvp_session.py`、`privacy.py`（日志脱敏）、`pilot_recorder.py`（问卷与记录）
- 新增 `stage6/host/production_host.py`：把 runtime 封装成可被 CLI 调用的 Host
- 新增 `packaging/`：PyInstaller spec、构建脚本、干净机测试清单
- 产物：Windows onedir 版 `ex-ai-pilot.exe`（免安装 Python，双击即用）
- 数据改为落在用户可写目录（`~/.ex_ai`），不再依赖安装目录可写

## 2026-11-21 发布前修复

- `requirements.txt`：把 `jsonschema`、`openai` 标为必需（原先只写了 Pillow，按文档安装会有 19/28 套件失败）；Pillow、anthropic 标为可选并注明用途
- `runtime/instance_persistence.py`：`correction_conflicts` 与 `persona_memory_builder` 的导入拆成两个 try，`f5e is None` 守卫移到首次使用之前（原先缺依赖时不是降级而是崩溃）
- `runtime/llm_gateway.py`：mock 回复改为固定占位文本，不再回显 prompt 尾部（原先会把人格设定片段吐进回复）
- 新增 `run_tests.py`：一条命令跑完 28 个套件，缺可选依赖记 SKIPPED，失败非 0 退出
- 新增 `.github/workflows/tests.yml`：ubuntu/windows × py3.10/3.13 的 CI
- 新增 `.gitattributes`：仓库统一存 LF（`.bat` 除外），修复 Windows 上 `core.autocrlf=true` 检出导致 frozen SHA 断言失败
- `evaluation/tests/test_eval_framework.py`：确定性比较忽略 `created_at`/`updated_at`（墙钟时间跨秒导致的偶发失败）
- `docs/COMPLIANCE.md`：按真实代码重写数据流向（真实模式会把人格块 + 命中的记忆 + 当前消息发给 DeepSeek，原文曾写"全部本地处理"）
- 从仓库移除本机绝对路径与运行产物（`e2e_out/`、`e2e_results/`、`stage59_e2e/*.json`、`dist_pkg_build.log`），加入 `.gitignore`
- 文档整理：`README(2) .md` → `docs/persona-memory-schema-v1-notes.md`；阶段报告移入 `docs/internal/`；`docs/EXPORT_GUIDE.md` → `docs/IMPORT_GUIDE.md`；`AGENTS.md` 精简为指向 `CLAUDE.md`
- 文档对齐代码：微信支持格式、版本存档时机、`/delete-ex` 的实现方式、社交媒体只做文件归类
- 统一 Python 版本声明为 3.10+（实测通过：3.10.20 与 3.13.14）
