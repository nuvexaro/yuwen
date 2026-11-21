#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 6.3 — 一键启动（普通用户友好入口）。Non-Frozen Product Surface。

目标：把首次启动简化为「运行 start → (如无 key) 输入 key → 自动配置 → 进入 CLI」。

安全：
  - API Key 只存在当前 Python 进程内存（os.environ）。
  - 不写入 config/.env/Git/pilot_data/日志/任何普通文本文件。
  - 退出程序后 Key 消失。
  - 不回显 key、不打印 key、不要求发给项目方。
  - 已通过环境变量配置过则不再询问。

流程：
  1. 若 DEEPSEEK_API 已在环境 → 直接用。
  2. 否则提示输入 key（不回显），set 到当前进程。
  3. 自动设 OPENAI_BASE_URL / EX_PROVIDER / EX_MODEL / EX_REAL。
  4. 启动现有 MVP CLI（pilot_recorder，可选 --user）。
不改 Host / Runtime / Frozen 语义。
"""

from __future__ import annotations

import getpass
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.join(_HERE, "..", "host"), os.path.join(_HERE, "..", ".."),
           os.path.join(_HERE, "..", "..", "benchmark")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _offline() -> bool:
    """EX_REAL=0 即离线模式：不建网络连接，不需要 API key。"""
    return os.environ.get("EX_REAL", "1") == "0"


def _resolve_key() -> str:
    """返回 key（来自 env 或用户输入）。只存内存，不落盘。"""
    env_key = os.environ.get("DEEPSEEK_API") or os.environ.get("OPENAI_API_KEY") or ""
    if env_key.strip():
        return env_key.strip()
    if _offline():
        return ""
    print("没有检测到已配置的 DeepSeek API Key。")
    print("请输入你的 Key（输入不会显示，回车确认；不会保存到任何文件）：")
    key = getpass.getpass("DeepSeek API Key: ").strip()
    if not key:
        print("未输入 Key，无法使用真实模型。退出。")
        sys.exit(2)
    return key


def _apply_defaults(key: str) -> None:
    """把 key + 默认 provider/model 配置到当前进程（仅内存）。"""
    # 离线模式（EX_REAL=0）没有 key，不要写入空串污染 DEEPSEEK_API / OPENAI_API_KEY
    if key:
        os.environ["DEEPSEEK_API"] = key
        os.environ.setdefault("OPENAI_API_KEY", key)      # real_llm_adapter 读 OPENAI_API_KEY
    os.environ.setdefault("OPENAI_BASE_URL", "https://api.deepseek.com")
    os.environ.setdefault("EX_PROVIDER", "openai")
    os.environ.setdefault("EX_MODEL", "deepseek-chat")
    os.environ.setdefault("EX_REAL", "1")
    # 用户可写数据根（正式 EXE 不写 bundle/_MEIPASS/_internal；不依赖 EXE 目录可写）
    from userdata import exes_dir, sessions_dir
    os.environ.setdefault("EX_BASE_DIR", exes_dir())
    os.environ.setdefault("EX_SESSION_DIR", sessions_dir())


def _selftest() -> int:
    """无 key / 无交互自检（EXE 验收用）：数据目录 + create + import + schema + 本地模块。

    返回 0 = 通过；非 0 = 失败。不触碰任何 Frozen。
    """
    import json, os as _os, tempfile as _tf
    # 强制用临时数据根，避免污染真实用户数据
    root = _os.path.join(_tf.gettempdir(), "exai_selftest")
    import shutil as _sh
    if _os.path.isdir(root):
        _sh.rmtree(root)
    _os.environ["EX_DATA_ROOT"] = root
    _apply_defaults("sk-selftest-dummy")
    from userdata import user_data_root, exes_dir
    ok = {"data_root_ok": user_data_root().startswith(root)}
    # 非打包(dev)模式：把 repo 的 tools/runtime/evaluation/benchmark 加进 sys.path
    if not getattr(sys, "frozen", False):
        _repo = _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", ".."))
        for _p in (_repo, _os.path.join(_repo, "tools"), _os.path.join(_repo, "runtime"),
                   _os.path.join(_repo, "evaluation"), _os.path.join(_repo, "benchmark")):
            if _p not in sys.path:
                sys.path.insert(0, _p)
    # local modules
    for m in ("persona_memory_builder", "evidence_extractor", "evidence_merge", "resolve_bundle",
              "import_pipeline", "eval_runner", "persona_runtime", "persona_loader",
              "instance_persistence", "skill_writer_v12", "production_host"):
        try:
            __import__(m)
        except Exception as e:
            ok[f"mod_{m}"] = False
    # schemas resolve
    import persona_memory_builder as pmb, evidence_extractor as ex, evidence_merge as em, import_pipeline as ip
    schema_paths = {"pm": pmb.PM_SCHEMA_PATH, "bundle": pmb.BUNDLE_SCHEMA_PATH,
                    "evidence": ex.SCHEMA_PATH, "merge": em.MERGE_SCHEMA_PATH, "message": ip.SCHEMA_PATH}
    ok["schemas"] = {k: _os.path.exists(v) for k, v in schema_paths.items()}
    # jsonschema/openai
    try:
        import jsonschema
        ok["jsonschema"] = True
    except Exception:
        ok["jsonschema"] = False
    try:
        import openai
        ok["openai"] = True
    except Exception:
        ok["openai"] = False
    # create Ex under user data root
    import skill_writer_v12 as sw12
    seed = {"schema_version": "1.2", "revision": 1,
            "persona": {"layer0_rules": {}, "identity": {"name_or_alias": {
                "claim_id": "pc_n", "value": "selftest", "evidence_ids": [], "confidence": 1.0,
                "basis": "user_report_only"}}, "speech_style": {}, "emotional_pattern": {},
                "relationship_behavior": {}},
            "memory": {k: [] for k in ("preferences", "timeline", "shared_experiences", "conflicts",
                                       "happy_memories", "breakup", "inside_jokes", "core_facts",
                                       "daily_patterns")}, "corrections": []}
    d = sw12.init_ex_instance(seed, exes_dir(), "selftest")
    ok["create_ex_under_userdata"] = d.startswith(root) and _os.path.exists(
        _os.path.join(d, "persona_memory.json"))
    # import sample（统一走 userdata.resolve_sample_path：EXE 根/_MEIPASS/cwd/开发仓库）
    from userdata import resolve_sample_path
    sample = resolve_sample_path()
    ok["import_chain"] = False
    if sample and _os.path.exists(sample):
        try:
            import eval_runner as er
            chat = json.load(open(sample, encoding="utf-8"))
            pm, _, errs = er.run_chain(chat, name="selftest")
            ok["import_chain"] = pm is not None and "persona" in pm
            if ok["import_chain"]:
                json.dump(pm, open(_os.path.join(exes_dir(), "selftest", "persona_memory.json"), "w",
                                   encoding="utf-8"), ensure_ascii=False, indent=2)
        except Exception as e:
            ok["import_err"] = str(e)
    print("SELFTEST=" + json.dumps(ok, ensure_ascii=False))
    passed = (ok.get("data_root_ok") and ok.get("create_ex_under_userdata")
              and ok.get("import_chain") and ok.get("jsonschema")
              and all(ok.get("schemas", {}).values()))
    return 0 if passed else 1


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in argv:
        return _selftest()
    # 可选 --user <id> 传给 pilot_recorder
    user = None
    if "--user" in argv:
        i = argv.index("--user")
        if i + 1 < len(argv):
            user = argv[i + 1]
    key = _resolve_key()
    _apply_defaults(key)
    if _offline():
        print("（离线模式：EX_REAL=0，不联网、不发请求；回复是固定占位文本）")
    # 启动现有 MVP CLI（pilot_recorder 引导；同一进程 → key 只在此进程内存）
    import pilot_recorder
    pilot_recorder.run_pilot(user_id=user)
    return 0


if __name__ == "__main__":
    sys.exit(main())
