# 数据与隐私合规说明

本文档描述本项目**实际的数据流向**，以当前代码为准（核对依据见文末）。
如果你发现文档与代码不一致，以代码为准，并请提 issue。

**一句话**：数据默认全部存在你自己的电脑上；只有当你**使用真实模型**时，每一次对话请求会把
「人格设定 + 命中的记忆片段 + 最近几轮 + 你这句」发送给模型服务商（默认 DeepSeek）。
离线模式不发任何网络请求。

---

## 1. 数据存在哪里

### 1.1 命令行 / EXE 版（`stage6/cli/`）

所有用户数据集中在**一个数据根目录**，默认 `<用户主目录>\.ex_ai\`
（Windows 为 `%USERPROFILE%\.ex_ai\`，其他系统为 `~/.ex_ai/`），可用环境变量 `EX_DATA_ROOT` 覆盖。

| 子目录 / 文件 | 内容 |
|---|---|
| `exes/<slug>/persona_memory.json` | 该 Ex 的**唯一**长期事实源：人格（5 层）+ 记忆 + 纠正记录 |
| `exes/<slug>/versions/` | 每次写回前的版本快照（用于回滚） |
| `exes/<slug>/SKILL.md`、`chat.py`、`meta.json` | 分发壳与入口，**不含**人格/记忆事实 |
| `sessions/<slug>/<session_id>.json` | 每个会话的完整对话历史（含你的原话与模型回复） |
| `pilot_data/` | 仅 Pilot 版：行为指标 + 你填写的问卷回答 |
| `exai_llm_diag.log` | 真实模型调用的**诊断日志**（见 §1.3） |

### 1.2 作为 Claude Code Skill 使用时

生成的 Skill 写在**你当前项目目录**下的 `./exes/<slug>/`（见 `SKILL.md`「基础目录」一节），
即落在你自己的仓库里。`exes/` 已在 `.gitignore` 中，默认不会被提交到 git。

### 1.3 诊断日志写了什么

每次调用真实模型成功/失败，会向数据根目录的 `exai_llm_diag.log` **追加一行**：
时间戳、provider、base_url、模型名、是否成功、异常类型、HTTP 状态码、以及脱敏后的异常信息（截断 300 字）。
**不包含** API key、请求头、你的对话正文。

---

## 2. 使用真实模型时，具体发送什么

**触发条件**：`EX_REAL` 不为 `0`（默认 `1`）且提供了 API key。

**发送目标**：一次 HTTP 请求发往 `OPENAI_BASE_URL`，默认 `https://api.deepseek.com`；
模型默认 `deepseek-chat`（可由 `EX_MODEL` 覆盖）。

**每一轮对话发送的内容**（请求体是**单条 user 消息**，内容为下面两块的拼接）：

| 块 | 是否发送 | 说明 |
|---|---|---|
| 当前这一轮你说的话 | ✅ 每轮 | 原文 |
| 系统块（人格设定） | ✅ 每轮 | 由 `persona_memory` 渲染：硬规则（L0）、身份（L1）、说话风格（L2，含口头禅/语气/标点习惯）、情绪模式（L3）、关系行为（L4） |
| 命中的记忆片段 | ✅ 命中才发 | 按当前这句检索出的 memory item，不是全部记忆 |
| 你此前确认过的纠正 | ✅ 有则发 | 渲染为「用户已纠正，务必遵守」小块 |
| 最近几轮对话 | ✅ 有则发 | 有 token 预算上限（默认约 2000 token 估算），超预算按固定顺序裁剪 |
| 原始聊天记录文件 / 照片 / 截图 | ❌ **不发** | 只在导入阶段本地解析，不进对话请求 |
| 完整的 `persona_memory.json` | ❌ **不发** | 只发渲染后的文本块，且受预算裁剪 |
| API key | 只作为鉴权头发给模型服务商 | 不进入 prompt 正文，不写盘 |

> 重要：**记忆和人格是你提炼后的事实，但其中可能包含对方的真实信息**（口头禅、共同经历、地点、习惯等）。
> 一旦使用真实模型，这些内容就会被发送到模型服务商。

---

## 3. 作为 Claude Code Skill 使用时

Skill 模式没有本项目自己的网络请求。但当你在 Claude Code 里触发 `/create-ex` 或 `/{slug}` 时：

- Claude Code 会用 `Read` 工具读取你指定的聊天记录、照片、生成的 `persona_memory.json` 等文件；
- 这些**被读取的内容会进入 Claude（Anthropic）的上下文**，按 Anthropic 的使用政策处理；
- 之后每一轮对话也由 Anthropic 提供服务。

也就是说：**Skill 模式下数据流向 Anthropic；CLI/EXE 模式下数据流向你配置的模型服务商（默认 DeepSeek）。**

如果你配置了 `EX_PROVIDER=anthropic` 走 Anthropic 官方接口，同样按 Anthropic 政策处理。

---

## 4. API key 怎么处理

| 项 | 实际情况 |
|---|---|
| 来源 | 环境变量 `DEEPSEEK_API` 或 `OPENAI_API_KEY`；都没有时启动会提示输入（不回显） |
| 存放位置 | **仅当前进程内存**（`os.environ`），进程结束即消失 |
| 是否写盘 | **否**。不写 `.env`、不写配置文件、不写 `persona_memory.json`、不写 `pilot_data`、不写日志 |
| 日志中是否出现 | 否。日志经 `privacy.redact()` 脱敏，key 形态的串会被替换为 `[REDACTED]` |
| 例外 | 如果你自己把 key 配成了**系统环境变量**，那是操作系统保存的，与本项目无关 |

---

## 5. 离线模式（不联网）

设置 `EX_REAL=0` 即进入离线模式：使用本地 mock 回复，**不建立任何网络连接**。

另外，即使 `EX_REAL` 保持默认，只要**没有可用的 key**（或 `openai` SDK 未安装），
程序会降级为离线 mock，也不会发请求——只是回复内容是无意义的占位文本。

离线模式下可完整走通：创建 Ex → 导入聊天记录 → 生成人格/记忆 → 多轮对话 → 纠正 → 落盘 → 重开验证。

---

## 5.1 本地模型模式（`YUWEN_BACKEND=local`）

设置 `YUWEN_BACKEND=local`（在启动菜单里选「2) 本地模型」等价）后，模型调用改为本机 Ollama：

- 请求发往 `http://localhost:11434/v1`（可用 `OPENAI_BASE_URL` 覆盖），**不出本机**。
- 不要求 API key；`OPENAI_API_KEY` 只是给 openai SDK 的占位串 `local-no-key`，不参与任何网络认证。
- 提示词内容（人格块 + 命中的记忆 + 当前消息）仍然会组成一次请求，只是收件方变成了本机的 Ollama 进程。
- 因此**数据不离开本机**：没有第三方服务器参与，也没有遥测。
- 注意：Ollama 自身会读你本机的模型文件；它的行为不在本项目控制范围内。

代码位置：`benchmark/real_llm_adapter.py` 的 `backend()` / `apply_local_defaults()` / `openai_adapter`，
`stage6/cli/start.py` 的 `_choose_backend()` / `_ollama_ready()`。

---

## 6. 明确不会发生的事

- 不上传原始聊天记录导出文件、照片、截图到任何服务器
- 不上传完整的 `persona_memory.json`
- 不向本项目作者或任何第三方回传使用数据；项目**没有**遥测、埋点、崩溃上报
- 不抓取微信/QQ 数据；聊天记录必须由你自己导出后交给程序
- 不主动联系、查找、验证现实中的任何人

---

## 7. 使用者须知（重要）

1. **聊天记录里包含对方的个人信息**（对方说的话、称呼、生活习惯、位置线索等）。
   这些数据属于你**和对方**，不是你一个人的。
2. **请只导入你有权使用的记录**：你自己参与的对话、你自己拍的照片、你自己写下的描述。
   不要导入通过破解、盗号、偷拍、他人转发等途径获得的材料。
3. **仅供个人使用**。不要公开分享生成的人格、对话内容或截图；不要用于骚扰、跟踪、冒充、诈骗。
4. **不要用于商业用途或传播**，也不要用于生成涉及未成年人的任何内容。
5. 生成的人格是**基于你的材料做的推断**，不是真实的对方，也不代表对方的真实想法。
6. 不同司法辖区对个人数据保护的要求不同，请遵守你所在地的法律。本项目仅提供技术工具，不构成法律建议。

---

## 8. 心理健康提示

本项目的初衷是帮助用户完成情感记忆的数字化存档，而非替代真实的人际关系。如果你在使用过程中发现自己：

- 无法停止与 AI 人格对话，影响了正常生活
- 产生了想要联系前任的强烈冲动
- 情绪持续低落或出现自伤想法

请暂停使用，并考虑寻求专业心理咨询帮助。

---

## 附：本说明的代码核对依据

| 结论 | 代码位置 |
|---|---|
| 数据根目录 `<home>/.ex_ai`，可被 `EX_DATA_ROOT` 覆盖；子目录 exes/sessions/pilot_data | `stage6/cli/userdata.py:58-83` |
| key 只从 env 读取或隐藏输入，仅写入 `os.environ`，不落盘 | `stage6/cli/start.py:35-56` |
| 默认服务商与地址：`EX_PROVIDER=openai`、`OPENAI_BASE_URL=https://api.deepseek.com`、`EX_MODEL=deepseek-chat` | `stage6/cli/start.py:50-56` |
| 默认 base_url 兜底为 DeepSeek，不落 OpenAI 官方 endpoint | `benchmark/real_llm_adapter.py:22`、`:159` |
| 请求体是**单条 user 消息**，content = 系统块 + 当前用户消息的拼接 | `runtime/llm_gateway.py:47`、`:82`；`benchmark/real_llm_adapter.py:131`（openai）、`:171`（anthropic） |
| 每轮只发 2 条消息（system 块 + 当前这句），不发完整历史 | `runtime/persona_runtime.py:128` |
| 系统块内容 = guardrail + L0/L1/L2/L3/L4 + 命中的 memory + 纠正 overlay | `runtime/persona_constraints.py:73`（`render_system_block`） |
| token 预算与裁剪顺序（默认 2000），禁止全量塞入 persona_memory | `runtime/context_assembly.py:1-9`、`:29` |
| 无 key / 无 SDK 时降级为离线 mock，不发请求 | `stage6/cli/mvp_cli.py:54-64` |
| `EX_REAL=0` 显式离线 | `stage6/cli/mvp_cli.py:60` |
| 诊断日志内容（时间/provider/base_url/model/异常，无 key 无正文） | `benchmark/real_llm_adapter.py:95-110` |
| 日志脱敏规则（`sk-…`、`api_key=`、长 hex → `[REDACTED]`） | `stage6/cli/privacy.py:18-28` |
| Pilot 记录只含行为指标 + 问卷回答，不含 key 与聊天正文 | `stage6/cli/pilot_recorder.py:49`、`:200-207` |
| 删除 Ex 时一并清掉 canonical + sessions + versions | `stage6/cli/mvp_cli.py:138`（`cmd_delete`） |

*本文档最后更新：2026-11-21（按真实代码重写）。*
