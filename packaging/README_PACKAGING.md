# ex-ai-pilot — Windows EXE 打包说明（Non-Frozen Distribution Layer）

## 产物目标

普通 Windows 用户：**下载 ZIP → 解压 → 双击 `ex-ai-pilot.exe` → 输入自己的 DeepSeek API Key → 进入 Pilot**。
无需安装 Python / pip / 依赖；无需 PowerShell / 环境变量。

## 如何构建

在项目根运行（需本机有 Python 3.10+ 与 PyInstaller）：

```bat
python -m pip install pyinstaller
packaging\build.bat
```

产物：
- `dist_pkg\dist\ex-ai-pilot\` —— onedir 可运行目录（含 `ex-ai-pilot.exe`）
- `dist_pkg\ex-ai-pilot.zip` —— 可分发的 ZIP

## 数据目录（用户可写）

用户运行时数据写到 **`%USERPROFILE%\.ex_ai\`**：
```
.ex_ai\exes\        # 每个 Ex 的 canonical persona_memory.json
.ex_ai\sessions\    # 会话状态
.ex_ai\pilot_data\  # Pilot 反馈记录
```
- 不写 PyInstaller bundle / `_MEIPASS` / `_internal`。
- 不依赖 EXE 所在目录可写。
- 可用环境变量 `EX_DATA_ROOT` 覆盖（开发/测试）。
- 不改变 persona_memory schema / 内容语义 / instance_persistence 语义。

## 内置示例

`sample_messages.json` 随 EXE 分发放于 dist 根；Pilot「导入→选项A」用它（经 `EX_SAMPLE_IMPORT` 或 dist 根）。

## API Key 安全（保持原设计）

- 用户输入自己的 Key，`getpass` **不回显**。
- Key 只存在当前进程内存。
- 不写 `.env` / config / pilot_data / 日志；不打包任何 Key；不打印/上传。
- 退出程序后 Key 消失。
- 已设系统环境变量 `DEEPSEEK_API` / `OPENAI_API_KEY` 的用户不重复询问。

## 打进去了什么

- tools / runtime / evaluation / stage6 的本地模块（hiddenimports）
- 5 个 `.schema.json`（复制到 dist 根，配合模块 `__file__` 相对加载）
- `openai` + `jsonschema`（第三方运行依赖）
- `sample_messages.json`

## 已知限制

- onedir（非 onefile）：ZIP 解压后是一个目录。
- 未做 installer / 自动更新 / 云端 Key 托管 / Web。
- 若双击后窗口一闪而过：在命令行跑 `ex-ai-pilot.exe` 查看报错。
- 聊天中孤立“她”可能无法解析指代（项目 Known Limit，不在 EXE 层处理）。

## 边界

本打包层仅动 Non-Frozen Product Surface / Distribution；不改 AI Core / Runtime / Host / CLI 业务语义 / Frozen SHA。
