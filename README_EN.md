# yuwen

Distill an ex into a conversational AI skill — their catchphrases, their tone, the places you went together.

[中文](README.md) · [Changelog](CHANGELOG.md) · [Privacy & data flow](docs/COMPLIANCE.md) · [Install guide](INSTALL.md)

---

## ⚠️ Notice

**This project is a derivative of [therealXiaomanChu/ex-skill](https://github.com/therealXiaomanChu/ex-skill).**
The original is MIT © therealXiaomanChu. This repository keeps that copyright notice and adds substantial changes
(data contracts, import pipeline, conversation runtime, correction loop, evaluation, CLI and a Windows build).
**See [CHANGELOG.md](CHANGELOG.md) for what actually changed.**

For personal reflection and emotional healing only. **Not for harassment, stalking, impersonation, or privacy invasion.**

---

## What it can do

| Feature | Status | Notes / what's missing |
|---|---|---|
| Import WeChat logs | ✅ Done, tested | Only `wechatmsg_txt` (WeChatMsg-style export) and `liuhen_json` (留痕-style export); **csv / html / sqlite not supported** |
| Import QQ logs | ✅ Done, tested | txt and `.mht/.mhtml` |
| Import social media | ⚠️ Partial | Only file classification + first 5000 chars of text; screenshots rely on Claude's vision; **no automatic persona extraction** |
| Import photos | ⚠️ Partial | Reads EXIF (time / place), requires Pillow; **no automated test** |
| Build persona + memory | ✅ Done, tested | evidence → merge → resolve → `persona_memory.json` (v1.2) |
| Conversation | ✅ Done, tested | Persona constraints + memory retrieval + session persistence; output quality depends on the model you plug in |
| Correction ("they wouldn't say that") | ✅ Done, tested | Proposal → confirm → atomic write-back + version snapshot; MVP only fixes the first correctable item in speech style |
| Versioning & rollback | ✅ Done, tested | Auto-backup on confirmed correction write-back; other updates need a manual `version_manager --action backup` |
| `/create-ex` | ⚠️ Partial | Requires installing into `.claude/skills/create-ex` first; no automated test |
| `/{slug}` chat | ⚠️ Partial | Works after an instance is generated; no end-to-end test |
| Privacy & compliance | ✅ Done | Data flow rewritten against the actual code — see [COMPLIANCE.md](docs/COMPLIANCE.md) |
| Export | ⚠️ Partial | No one-command export; only correction-proposal export and instance file generation |

---

## Privacy & data flow (read this first)

All data lives on your own machine (CLI/EXE: `~/.ex_ai/`; skill mode: `./exes/` in your project).
**In real-model mode**, every turn sends "the persona system block + the memory items retrieved for this turn + recent turns + your message" to the model provider — **DeepSeek** by default (`https://api.deepseek.com`). Original chat-log files, photos and the full `persona_memory.json` are **not** sent.
**Offline mode** (`EX_REAL=0`) makes no network connections at all.
**As a Claude Code skill**, the files Claude reads (chat logs, generated persona files) enter Anthropic's context.
Imported chat logs contain **the other person's personal data** — only import records you have the right to use, and keep it for personal use.

Full statement with per-item code references: [docs/COMPLIANCE.md](docs/COMPLIANCE.md)

---

## Installation

### A. As a Claude Code skill

```bash
# run at the root of the project where you want to use it
mkdir -p .claude/skills
git clone https://github.com/nuvexaro/yuwen .claude/skills/create-ex
```

Then type `/create-ex` in Claude Code.
(Global install: `git clone https://github.com/nuvexaro/yuwen ~/.claude/skills/create-ex`)

### B. Run the CLI from source

Requires Python 3.10 or newer.

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

### C. Windows portable build

Download `ex-ai-pilot.zip` from [https://github.com/nuvexaro/yuwen/releases](https://github.com/nuvexaro/yuwen/releases), unzip and double-click `ex-ai-pilot.exe`.
Enter your own DeepSeek API key when prompted (input is hidden and never written to disk). No Python needed.

---

## Quick start

### Offline trial (no API key, no network)

Run from the repository root. All four commands are verified to work:

```bash
# 1. enter the CLI directory
cd stage6/cli

# 2. create a persona instance ("demo" is the slug, pick your own)
python mvp_cli.py create --slug demo --name 小明

# 3. import the sample chat log shipped with the repo
python mvp_cli.py import --ex demo --chat ../../evaluation/dataset/case_001/messages.json --name 小明

# 4. start chatting (type /quit to exit)
python mvp_cli.py chat --ex demo
```

Before step 4, set `EX_REAL` to `0` (or simply provide no key — the program falls back to offline automatically):

```bash
# macOS / Linux
export EX_REAL=0
# Windows PowerShell
$env:EX_REAL='0'
# Windows cmd
set EX_REAL=0
```

Offline replies are a fixed placeholder (`[离线模式] 这是测试回复，未连接真实模型。`). They only prove the pipeline works — **they say nothing about reply quality**.

### Real mode (needs your own DeepSeek API key)

```bash
# macOS / Linux
export DEEPSEEK_API='your key'
# Windows PowerShell
$env:DEEPSEEK_API='your key'

cd stage6/cli
python start.py
```

`start.py` sets `OPENAI_BASE_URL=https://api.deepseek.com` and `deepseek-chat`, then walks you through the flow.
The key stays in process memory only and is never written to disk. You can also run `python mvp_cli.py chat --ex demo` directly on an existing instance.

---

## Running tests

```bash
python run_tests.py
```

Runs all 28 suites in about 20 seconds; exits non-zero on any failure.
Suites that fail only because an optional dependency (`anthropic`, `Pillow`) is missing are reported as SKIPPED.
Run a subset: `python run_tests.py -k runtime`.

CI: `.github/workflows/tests.yml` (ubuntu-latest / windows-latest × Python 3.10 / 3.13).

---

## Project layout

```
.
├─ SKILL.md                   # Claude Code skill entry (frontmatter + main flow)
├─ prompts/                   # 9 prompt templates (intake / persona / memory / merge / correction …)
├─ tools/                     # 20 Python tools (parsers, evidence, builder, versioning) + tests
├─ runtime/                   # 14 runtime modules (constraints, retrieval, correction, persistence) + tests
├─ stage6/cli/                # Pilot CLI (create / import / chat / delete)
├─ stage6/host/               # Production Host (wraps the runtime as a callable service)
├─ evaluation/                # 14 golden cases, eval framework, report aggregation
├─ benchmark/                 # runtime case set, harness, result records
├─ packaging/                 # PyInstaller spec and clean-machine checklist
├─ docs/                      # COMPLIANCE / PRD / IMPORT_GUIDE / internal (stage records)
├─ *.schema.json              # 5 frozen JSON Schemas (data contracts)
├─ requirements.txt
├─ run_tests.py               # single test entry point
├─ CHANGELOG.md               # changes vs upstream
└─ CLAUDE.md / AGENTS.md      # project constraints (AGENTS.md points to CLAUDE.md)
```

---

## Known limitations

1. **Retrieval is rule-based, not vector-based** — long sessions with zero lexical overlap (e.g. correct "she's chatty", then talk about unrelated things, then ask "do you think she's easy to get along with?") may fail to recall, and the model will ask "which she?".
2. **Reality boundary only covers time-related conflicts** — detected by year collision; non-temporal conflicts (e.g. two places with the same name) are not covered.
3. **Correction only targets the first correctable item** — the MVP fixes the first correctable claim in speech style (L2); no multi-candidate routing.
4. **Persona claims have no independent status/supersede** — a v1.2 schema limitation; corrected state can only be inferred from top-level `corrections[]` (see `evaluation/known_schema_limits.md`).
5. **Semantic quality needs human evaluation** — automation only covers schema / provenance / determinism / conflict assertions; "does it sound like them" needs human raters.

A few more **feature gaps** (documented as-is, not papered over):

- WeChat only supports `wechatmsg_txt` / `liuhen_json`; **csv / html are not supported**
- Social-media import only classifies files; **no automatic persona extraction**
- `/delete-ex` and `/let-go` are **instructions to the agent** (`rm -rf exes/{slug}`), not standalone tools; the CLI equivalent is `mvp_cli.py delete --ex {slug}`
- No one-command export

---

## Credits

Original project: [therealXiaomanChu/ex-skill](https://github.com/therealXiaomanChu/ex-skill) by therealXiaomanChu.
Changes in this repository: [CHANGELOG.md](CHANGELOG.md).

## License

MIT. Original © 2026 therealXiaomanChu; modifications © 2026 nuvexaro. See [LICENSE](LICENSE).
