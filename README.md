# yuwen（余温）

[![tests](https://github.com/nuvexaro/yuwen/actions/workflows/tests.yml/badge.svg)](https://github.com/nuvexaro/yuwen/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Latest release](https://img.shields.io/github/v/release/nuvexaro/yuwen)](https://github.com/nuvexaro/yuwen/releases/latest)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://python.org)

把前任的聊天记录、照片和你的描述，蒸馏成一个能对话的 AI Skill —— 用 ta 的口头禅、ta 的语气，记得你们一起去过的地方。

[English](README_EN.md) · [改动记录](CHANGELOG.md) · [隐私与数据流向](docs/COMPLIANCE.md) · [安装详解](INSTALL.md)

---

## ⚠️ 声明

**本项目基于 [therealXiaomanChu/ex-skill](https://github.com/therealXiaomanChu/ex-skill) 修改。**
原项目 MIT © therealXiaomanChu，本仓库保留原版权声明，并在此基础上做了较大改造（数据合同、导入管线、对话运行时、纠正闭环、评测、CLI 与 Windows 打包）。
**具体改了什么见 [CHANGELOG.md](CHANGELOG.md)。**

本项目仅用于个人回忆与情感疗愈，**不用于骚扰、跟踪、冒充或侵犯他人隐私**。

---

## 下载

⬇️ **[最新版本下载页](https://github.com/nuvexaro/yuwen/releases/latest)**

| 版本 | 适合谁 | 说明 |
|---|---|---|
| **Windows 安装版**（`yuwen-v*-setup-windows-x64.exe`） | 普通用户 | 双击安装，自动创建开始菜单快捷方式（桌面快捷方式可选），可在「设置 → 应用」里卸载 |
| **免安装版**（`yuwen-v*-windows-x64.zip`） | 不想安装 / 想放 U 盘 | 解压后双击 `ex-ai-pilot.exe`，不用装 Python |

- **普通用户**：装好之后先看 [快速开始](#快速开始)，只需要一个 DeepSeek API Key
- **开发者**：从源码跑见 [从源码运行 CLI](#b-从源码运行-cli)，跑测试见 [运行测试](#运行测试)

---

## 它能做什么

| 功能 | 状态 | 说明 / 缺什么 |
|---|---|---|
| 导入微信聊天记录 | ✅ 已完成，有测试 | 仅支持 `wechatmsg_txt`（WeChatMsg 类导出）与 `liuhen_json`（留痕类导出）；**csv / html / sqlite 暂不支持** |
| 导入 QQ 聊天记录 | ✅ 已完成，有测试 | 支持 txt 与 `.mht/.mhtml` |
| 导入朋友圈 / 社交媒体 | ⚠️ 部分完成 | 只做文件归类 + 文本前 5000 字；截图内容依赖 Claude 读图；**没有自动抽取人设** |
| 导入照片 | ⚠️ 部分完成 | 能读 EXIF（时间/地点），需装 Pillow；**没有自动化测试** |
| 生成人格 + 记忆 | ✅ 已完成，有测试 | 证据抽取 → 合并 → 解析 → `persona_memory.json`（v1.2） |
| 对话 | ✅ 已完成，有测试 | 人格约束 + 记忆检索 + 会话持久化；回复质量取决于所接模型 |
| 纠正（「ta 不会这么说」） | ✅ 已完成，有测试 | 产生纠正建议 → 确认 → 原子写回 + 版本快照；MVP 只纠正说话风格里第一个可纠条目 |
| 版本管理与回滚 | ✅ 已完成，有测试 | 确认纠正写回时自动备份；其他更新需手动 `version_manager --action backup` |
| `/create-ex` | ⚠️ 部分完成 | 需先把仓库装到 `.claude/skills/create-ex`；无自动化测试 |
| `/{slug}` 对话 | ⚠️ 部分完成 | 生成实例后可用；无端到端测试 |
| 隐私与合规 | ✅ 已完成 | 数据流向按代码重写，见 [COMPLIANCE.md](docs/COMPLIANCE.md) |
| 导出成品 | ⚠️ 部分完成 | 没有一键导出命令；只有 correction proposal 导出与实例文件生成 |

---

## 架构

```mermaid
flowchart LR
    subgraph IMP["① 导入链（离线、一次性）"]
        A1["聊天记录<br/>txt / json"] --> A2["parser<br/>wechat_parser / qq_parser"]
        A2 --> A3["Message<br/>message.schema v1.2"]
        A3 --> A4["证据抽取<br/>evidence_extractor"]
        A4 --> A5["证据合并<br/>evidence_merge"]
        A5 --> A6["裁决<br/>resolve_bundle"]
        A6 --> A7[("persona_memory.json<br/>v1.2")]
    end

    subgraph CHAT["② 对话链（在线、每轮一次）"]
        B1["用户输入"] --> B2["现实预检<br/>reality_boundary"]
        B2 --> B3["记忆检索<br/>memory_retrieval"]
        B3 --> B4["组装上下文<br/>context_assembly"]
        B4 --> B5["LLM 网关<br/>llm_gateway"]
        B5 --> B6["回复"]
    end

    subgraph FIX["③ 纠正分支"]
        C1["识别纠正<br/>correction_runtime"] --> C2["冲突检查<br/>correction_conflicts"]
        C2 --> C3["用户确认"]
        C3 --> C4["备份并写回<br/>instance_persistence"]
    end

    A7 -. 加载人格/记忆 .-> B3
    B1 -. 说"不对…" .-> C1
    C4 -. revision + 1 .-> A7
```

核心设计只有一条：**人格里的每一条内容都能追溯到原始消息**。记忆条目身上带着 `evidence_ids`，指向证据候选；候选带着 `supporting_message_ids`，指向原始 `Message`。所以模型不能凭空替对方"回忆"——它想说的话必须能落到某条有出处的记录上，落不到就该说"我不太确定"。

另外两条链是解耦的：导入链只写 `persona_memory.json`，对话链只读它。中间靠 JSON Schema 卡住格式，改一边不会悄悄破坏另一边。

---

## 隐私与数据流向（请先读这段）

所有数据默认存在你自己的电脑上（CLI/EXE 版在 `~/.ex_ai/`，Skill 版在你项目的 `./exes/`）。
**使用真实模型时**，每一轮对话会把「人格设定块 + 本次命中的记忆片段 + 最近几轮 + 你这句」发给模型服务商，默认是 **DeepSeek**（`https://api.deepseek.com`）；不会发送原始聊天记录文件、照片或完整的 `persona_memory.json`。
**离线模式**（`EX_REAL=0`）不建立任何网络连接。
**作为 Claude Code Skill 使用时**，被读取的聊天记录与生成文件会进入 Anthropic 的上下文。
导入的聊天记录里包含**对方的个人信息**，请只导入你有权使用的记录，并仅作个人使用。

完整说明（含逐条代码依据）：[docs/COMPLIANCE.md](docs/COMPLIANCE.md)

---

## 安装

### A. 作为 Claude Code Skill 使用

```bash
# 在你要使用它的项目根目录执行
mkdir -p .claude/skills
git clone https://github.com/nuvexaro/yuwen .claude/skills/create-ex
```

然后在 Claude Code 里输入 `/create-ex`。
（也可以装到全局：`git clone https://github.com/nuvexaro/yuwen ~/.claude/skills/create-ex`）

### B. 从源码运行 CLI

需要 Python 3.10 或以上。

```bash
git clone https://github.com/nuvexaro/yuwen yuwen
cd yuwen

python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

python -m pip install -r requirements.txt
cd stage6/cli
python mvp_cli.py --help
```

### C. Windows 安装版 / 免安装版

去 [下载页](https://github.com/nuvexaro/yuwen/releases/latest) 取最新版：

- **安装版**：`yuwen-v*-setup-windows-x64.exe`，双击 → 选择安装位置（默认 `%LOCALAPPDATA%\Programs\yuwen`，**不需要管理员权限**）→ 安装完可以直接勾选「立即运行 yuwen」。
- **免安装版**：`yuwen-v*-windows-x64.zip`，解压后双击 `ex-ai-pilot.exe`。不需要安装 Python。

两种方式都不需要预装 Python；第一次启动会提示输入 DeepSeek API Key（输入不回显、只存在内存里，不落盘）。

**只想先看看流程（离线试用）**：在程序目录里打开 cmd，运行

```bat
set EX_REAL=0
ex-ai-pilot.exe
```

离线模式不联网、不需要 API Key，但回复是固定的占位句（`[离线模式] 这是测试回复，未连接真实模型。`），**只能确认流程能走通**。要真实对话，仍然需要提供 DeepSeek API Key（见 [获取 DeepSeek API Key](#获取-deepseek-api-key)）。

---

## Windows 安全提示

第一次运行安装包或 `ex-ai-pilot.exe` 时，Windows 可能弹出蓝色的「**Windows 已保护你的电脑**」（SmartScreen）。

**原因**：这是一个免费开源项目，没有购买代码签名证书（一张证书一年几百到上千元），Windows 对"下载量少、无签名"的新程序默认拦截。**不是**因为程序有毒。

**处理方法**：

1. 点弹窗里的「**更多信息**」
2. 点右下角出现的「**仍要运行**」

**如果还是不放心**，可以核对文件哈希：Release 页面会公布每个文件的 SHA256，下载后自己算一遍对比。

```powershell
# 在下载文件所在目录打开 PowerShell
Get-FileHash .\yuwen-v0.1.1-setup-windows-x64.exe -Algorithm SHA256
```

哈希一致说明文件没被替换过。代码全部公开在 https://github.com/nuvexaro/yuwen ，也可以直接自己从源码构建。

---

## 快速开始

### 用安装包装好之后（推荐普通用户）

1. 装完在开始菜单里找到 **yuwen** 打开（安装时勾了桌面快捷方式的话，桌面上也有）
2. 第一次运行会提示输入 DeepSeek API Key → 粘贴，回车（输入不回显）
3. 按引导走：起个代号 → 导入聊天记录 → 开始聊天

想要更省事的做法是提前把 key 设成环境变量，这样启动时就不再询问：

```bat
set DEEPSEEK_API=你的key
```

```powershell
# PowerShell
$env:DEEPSEEK_API='你的key'
```

> 注意：`set` / `$env:` 只对**当前这个命令行窗口**有效。想永久生效要到「系统属性 → 环境变量」里加，但那样 key 会被 Windows 保存到磁盘（见第 2 条的说明）。

### 离线体验（不需要 API Key，不联网）

以下命令在仓库根目录执行，全部已验证可跑通：

```bash
# 1. 进入 CLI 目录
cd stage6/cli

# 2. 创建一个人格实例（demo 是代号，可自定义）
python mvp_cli.py create --slug demo --name 小明

# 3. 导入仓库自带的示例聊天记录
python mvp_cli.py import --ex demo --chat ../../evaluation/dataset/case_001/messages.json --name 小明

# 4. 开始对话（输入 /quit 退出）
python mvp_cli.py chat --ex demo
```

第 4 步之前把 `EX_REAL` 设为 `0`（或干脆不配 Key，程序会自动降级到离线）：

```bash
# macOS / Linux
export EX_REAL=0
# Windows PowerShell
$env:EX_REAL='0'
# Windows cmd
set EX_REAL=0
```

离线模式的回复是固定的占位文本（`[离线模式] 这是测试回复，未连接真实模型。`），只用来验证流程跑通，**不代表回复质量**。

### 真实模式（需要自己的 DeepSeek API Key）

```bash
# macOS / Linux
export DEEPSEEK_API='你的 key'
# Windows PowerShell
$env:DEEPSEEK_API='你的 key'

cd stage6/cli
python start.py
```

`start.py` 会配置好 `OPENAI_BASE_URL=https://api.deepseek.com` 与 `deepseek-chat`，然后进入引导。
Key 只在当前进程内存里，不写盘。也可以用 `python mvp_cli.py chat --ex demo` 直接进入已有实例。

---

## 使用本地模型（免费、无需 API Key、数据不出本机）

不想申请 API Key、或者不想让对话内容离开本机，可以用 **Ollama + Qwen3.5-4B** 在本机跑。
启动时选「2) 本地模型」即可，两种后端并存，随时切回云端。

### 硬件建议

| 显存 | 建议 | 说明 |
|---|---|---|
| ≥ 8 GB | `yuwen-4b-q8`（Q8_0，约 5.2 GB） | 质量最好。实测：加载后占 5.0 GB，显存峰值 **6757 MiB**，100% 在 GPU |
| ≥ 6 GB | `yuwen-4b-q4`（Q4_K_M，约 3.4 GB） | **默认值**。实测：加载后占 3.2 GB，显存峰值 **5116 MiB**，100% 在 GPU |
| 4 GB 左右 | `yuwen-4b-q4` | 可能要降低上下文（`PARAMETER num_ctx 2048`） |
| 无独显 | 换成 Qwen3.5-2B 之类的更小模型 | **未实测**，纯 CPU 会很慢（每轮几十秒量级） |

> 实测环境：RTX 4060 Laptop 8 GB（桌面已占约 2 GB）+ 16 GB 内存，上下文 4096，`ollama ps` 两个模型都是 **100% GPU**。

### 步骤

```bash
# 1. 安装 Ollama（只需一次）  https://ollama.com/download
#    装完确认它在后台运行：ollama list 能正常输出

# 2. 拉取模型（约 2.6 GB，只需一次）
ollama pull modelscope.cn/unsloth/Qwen3.5-4B-GGUF:Q4_K_M

# 3. 建一个 4096 上下文的别名（只需一次）
#    新建文本文件 Modelfile，写上两行：
#      FROM modelscope.cn/unsloth/Qwen3.5-4B-GGUF:Q4_K_M
#      PARAMETER num_ctx 4096
ollama create yuwen-4b-q4 -f Modelfile

# 4. 启动 yuwen，在菜单里选「2) 本地模型」
```

想用 Q8_0 就先 `ollama pull modelscope.cn/unsloth/Qwen3.5-4B-GGUF:Q8_0`、用同样的方式建别名 `yuwen-4b-q8`，
然后设环境变量 `EX_MODEL=yuwen-4b-q8`（`set EX_MODEL=yuwen-4b-q8` 或 `$env:EX_MODEL='yuwen-4b-q8'`）。

### 说明

- 本地模式**不需要 API Key**，也不会向外发任何请求；所有推理都在你的机器上完成。
- **效果会比云端大模型弱**：4B 模型在长对话里更容易忘记设定、语气更平。
- 本机实测（RTX 4060 Laptop 8 GB，4096 上下文，同一人格问 5 句话）：

  | | Q4_K_M | Q8_0 |
  |---|---|---|
  | 平均生成速度 | 14.3 token/s | 15.8 token/s |
  | 单轮耗时 | 2.8 – 4.1 s | 3.5 – 7.8 s |
  | 显存峰值 | 5116 MiB | 6757 MiB |
  | GPU 占比 | 100% | 100% |

- 一个反直觉的实测结论：**Q8 更流畅，但也更容易编**。问到"第一次见面"时，Q4 老老实实说"记不清了"，
  Q8 编出了"街角便利店、你手里拿着快过期的可乐"这种 persona 里根本没有的细节。
  如果你在意"不编造"，Q4 反而更安全。

---

## 获取 DeepSeek API Key

yuwen 默认走 DeepSeek。你需要自己的 key（不共享、按量计费）。

1. 打开 <https://platform.deepseek.com>
2. 注册 / 登录
3. 充值（充值入口在控制台里；具体活动与门槛以官网为准）
4. 进入 **API Keys** 页面 → **创建 API key** → 复制（**只显示一次**，关掉就看不到了）

**怎么填给 yuwen**，两种方式，任选其一：

- **启动时输入**：直接运行 `ex-ai-pilot.exe`（或 `python start.py`），程序检测不到 key 时会提示 `DeepSeek API Key:`，粘贴后回车。输入不回显。
- **提前设环境变量**：程序会优先读 `DEEPSEEK_API`（其次 `OPENAI_API_KEY`）：

  ```bat
  :: Windows cmd
  set DEEPSEEK_API=你的key
  ```

  ```powershell
  # Windows PowerShell
  $env:DEEPSEEK_API='你的key'
  ```

  ```bash
  # macOS / Linux
  export DEEPSEEK_API='你的key'
  ```

**key 会被怎么处理**（依据 `docs/COMPLIANCE.md` 与代码，如实说明）：

- **只存在当前进程的内存里**（`os.environ`），进程退出就没了；不会写进 `.env`、配置文件、`persona_memory.json`，也不会写进日志。
- 日志里出现的疑似 key 会被脱敏成 `[REDACTED]`。
- **如果你自己把 `DEEPSEEK_API` 加成了系统环境变量**，那是 Windows 存到磁盘上的，和本项目无关 —— 安全性取决于你这台电脑。
- 代价：不设环境变量的话，每次启动都要重新输入一次 key。

**费用**：DeepSeek 按 token 计费（输入/输出分别计价），具体单价以 <https://platform.deepseek.com> 官方价格页为准，这里不写死数字。日常聊天是"每轮几百到几千 token"的量级，先充一点点就够试。

---

## 怎么准备聊天记录

支持两种微信导出格式：**WeChatMsg 类工具导出的 txt** 和 **留痕类工具导出的 JSON**（QQ 支持 txt / mht）。

怎么导出、导出后长什么样、常见报错怎么处理，全部写在 **[docs/IMPORT_GUIDE.md](docs/IMPORT_GUIDE.md)**。

> 只导入你自己参与过的对话，聊天记录里有对方的个人信息。

---

## 运行测试

```bash
python run_tests.py
```

一条命令跑完 28 个测试套件（约 20 秒），失败会以非 0 退出码结束。
缺可选依赖（`anthropic`、`Pillow`）导致的失败会记为 SKIPPED。
只跑某一组：`python run_tests.py -k runtime`。

CI：`.github/workflows/tests.yml`（ubuntu-latest / windows-latest × Python 3.10 / 3.13）。

---

## 项目结构

```
.
├─ SKILL.md                   # Claude Code skill 入口（frontmatter + 主流程）
├─ prompts/                   # 9 个提示词模板（录入/人格/记忆/合并/纠正…）
├─ tools/                     # 20 个 Python 工具（解析、证据、构建、版本管理）+ 测试
├─ runtime/                   # 对话运行时 14 个模块（人格约束、检索、纠正、持久化）+ 测试
├─ stage6/cli/                # Pilot CLI（create / import / chat / delete）
├─ stage6/host/               # Production Host（把 runtime 封装成可调用服务）
├─ evaluation/                # 14 个 golden case、评测框架、报告聚合
├─ benchmark/                 # runtime 用例集、harness、结果记录
├─ packaging/                 # PyInstaller 打包与干净机测试清单
├─ docs/                      # COMPLIANCE / PRD / IMPORT_GUIDE / internal（阶段记录）
├─ *.schema.json              # 5 个冻结的 JSON Schema（数据合同）
├─ requirements.txt
├─ run_tests.py               # 一键测试入口
├─ CHANGELOG.md               # 相对上游的改动
└─ CLAUDE.md / AGENTS.md      # 项目约束（AGENTS.md 指向 CLAUDE.md）
```

---

## 卸载与删除数据

### 卸载程序

- **安装版**：打开「设置 → 应用 → 已安装的应用」，找到 **yuwen（余温）** → 卸载；或开始菜单里的「卸载 yuwen」。
- **免安装版**：直接删掉解压出来的那个文件夹就行（不写注册表、不装服务）。

**卸载不会删除你的数据。** 卸载向导最后会弹一个提示，告诉你数据在哪。

### 你的数据存在哪

| 内容 | 路径 |
|---|---|
| 全部数据根目录 | `%USERPROFILE%\.ex_ai\`（即 `C:\Users\<你的用户名>\.ex_ai\`） |
| 人格 + 记忆（每个 Ex 一份） | `.ex_ai\exes\<代号>\persona_memory.json` |
| 历史版本快照 | `.ex_ai\exes\<代号>\versions\` |
| 对话记录 | `.ex_ai\sessions\<代号>\<会话id>.json` |
| Pilot 问卷记录（如果用测试版跑过） | `.ex_ai\pilot_data\` |

> 用 Claude Code Skill 模式时，数据在**你自己项目**的 `./exes/` 下，不在 `.ex_ai`。

### 怎么彻底删掉

1. 先卸载程序（上面那步）
2. 手动删掉 `%USERPROFILE%\.ex_ai\` 整个文件夹（**删除后不可恢复**）

只想删某一个人格、保留其它的话，用命令行删单个 Ex：

```bash
cd stage6/cli
python mvp_cli.py delete --ex <代号>
```

它会一起清掉这个人格、对应的会话记录和历史版本。

---

## 已知限制

1. **检索是规则匹配，没有向量检索** —— 长会话 + 零字面重叠的问题（比如纠正「她话痨」后聊很多无关内容再问「你觉得她好相处吗」）可能召回不到，模型会反问「哪个她」。
2. **现实边界只覆盖时间类冲突** —— 用年份碰撞检测；地点同名之类的非时间事实冲突未覆盖。
3. **纠正只做第一个可纠条目** —— MVP 只纠正说话风格（L2）里第一个可纠的 claim，不支持多候选路由。
4. **persona claim 没有独立 status/supersede** —— schema v1.2 的结构限制，纠正后的状态只能从顶层 `corrections[]` 推断（见 `evaluation/known_schema_limits.md`）。
5. **语义质量靠人工评测** —— 自动化只覆盖 schema / provenance / 确定性 / 冲突等结构性断言；「像不像」需要真人打分。

另外几处**功能缺口**（文档已如实标注，不打算靠改文档掩盖）：

- 微信只支持 `wechatmsg_txt` / `liuhen_json`，**csv / html 不支持**
- 社交媒体导入只做文件归类，**没有人设自动抽取**
- `/delete-ex`、`/let-go` 是给 agent 的**删除指令**（`rm -rf exes/{slug}`），不是独立工具；CLI 里对应 `mvp_cli.py delete --ex {slug}`
- 没有一键导出成品包

---

## 致谢

原始项目：[therealXiaomanChu/ex-skill](https://github.com/therealXiaomanChu/ex-skill)，作者 therealXiaomanChu。
本仓库的改造工作见 [CHANGELOG.md](CHANGELOG.md)。

## License

MIT。原版权 © 2026 therealXiaomanChu；修改部分 © 2026 nuvexaro。详见 [LICENSE](LICENSE)。
