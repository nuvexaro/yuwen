# yuwen（余温）

把前任的聊天记录、照片和你的描述，蒸馏成一个能对话的 AI Skill —— 用 ta 的口头禅、ta 的语气，记得你们一起去过的地方。

[English](README_EN.md) · [改动记录](CHANGELOG.md) · [隐私与数据流向](docs/COMPLIANCE.md) · [安装详解](INSTALL.md)

---

## ⚠️ 声明

**本项目基于 [therealXiaomanChu/ex-skill](https://github.com/therealXiaomanChu/ex-skill) 修改。**
原项目 MIT © therealXiaomanChu，本仓库保留原版权声明，并在此基础上做了较大改造（数据合同、导入管线、对话运行时、纠正闭环、评测、CLI 与 Windows 打包）。
**具体改了什么见 [CHANGELOG.md](CHANGELOG.md)。**

本项目仅用于个人回忆与情感疗愈，**不用于骚扰、跟踪、冒充或侵犯他人隐私**。

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

### C. Windows 免安装版

到 [https://github.com/nuvexaro/yuwen/releases](https://github.com/nuvexaro/yuwen/releases) 下载 `yuwen-v0.1.0-windows-x64.zip`，解压后双击 `ex-ai-pilot.exe`，按提示输入自己的 DeepSeek API Key（输入不回显、不落盘）。不需要安装 Python。

**只想先看看流程（离线试用）**：在解压出来的目录里打开 cmd，运行

```bat
set EX_REAL=0
ex-ai-pilot.exe
```

离线模式不联网、不需要 API Key，但回复是固定的占位句（`[离线模式] 这是测试回复，未连接真实模型。`），**只能确认流程能走通**。要真实对话，仍然需要提供 DeepSeek API Key（就是上面那种启动方式）。

---

## 快速开始

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
