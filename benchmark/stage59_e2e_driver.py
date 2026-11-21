#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage: Real E2E Host Integration / Verification driver（E1-E6）。

在仓库外 host 缺席的前提下，本 driver 作为 External Host 的验证替身，执行已裁定的
host↔repo 契约（load_instance → make_runtime(real adapter) → respond_once → persist_confirmed）。
它不伪装成生产部署，也不使用 mock：真实 LLM = real_llm_adapter + DEEPSEEK_API。

E1 Ex creation（repo 原语）
E2 Real multi-turn conversation
E3 Correction proposal（真实用户确认由 operator 完成，driver 停在 proposal 供确认）
E4 Persistence（persist_confirmed → persona_memory.json）
E5 Cross-session（新 session 采用）
E6 Instance isolation

每个 stage 记录两层：repo/runtime state + real LLM output。API key 只经 env，绝不写入任何文件。
"""

from __future__ import annotations

import copy
import json
import os
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOOLS = os.path.join(ROOT, "tools")
for p in (os.path.join(ROOT, "runtime"), TOOLS, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)


def e1_create_ex(seed, base_dir, slug):
    """E1: 用 skill_writer_v12 从真实 v1.2 seed 建独立 Ex Instance。返回目录。"""
    import skill_writer_v12 as sw12
    sd = sw12.init_ex_instance(seed, base_dir, slug)
    with open(os.path.join(sd, "persona_memory.json"), encoding="utf-8") as f:
        on_disk = json.load(f)
    skill = open(os.path.join(sd, "SKILL.md"), encoding="utf-8").read()
    return sd, on_disk, skill


def e2_runtime(sd, adapter, model="deepseek-chat"):
    """E2: 建 real runtime（Host 替身）：load persona_memory.json → loader → PersonaRuntime(real)。"""
    import sys as _s
    _s.path.insert(0, sd)  # chat.py 在 ex dir
    from chat import load_instance, make_runtime
    pm_path = os.path.join(sd, "persona_memory.json")
    base, longterm = load_instance(pm_path)
    rt = make_runtime(base, adapter=adapter, model=model)
    return rt, pm_path


def make_real_adapter():
    import real_llm_adapter as rla
    return rla.make_provider_adapter("openai")  # reads OPENAI_API_KEY/OPENAI_BASE_URL from env


def new_seed():
    """真实 v1.2 seed：persona 小明 + core_fact 她话少(active) → 便于产生 correction。"""
    return {"schema_version": "1.2", "revision": 1,
            "persona": {"layer0_rules": {"do_not_say": [], "specific_edges": [], "reality_boundary": None},
                        "identity": {"name_or_alias": {"claim_id": "pc_n", "value": "小明", "evidence_ids": ["c1"],
                                                       "confidence": 1.0, "basis": "user_report_only"},
                                     "relationship": {}},
                        "speech_style": {"catchphrases": [{"claim_id": "pc_c", "value": "哈哈哈哈",
                                                           "evidence_ids": ["c1"], "confidence": 0.9,
                                                           "basis": "direct_quote"}],
                                         "examples": [], "punctuation": None,
                                         "tone": [{"claim_id": "pc_t", "value": "简短冷淡", "evidence_ids": ["c1"],
                                                   "confidence": 0.9, "basis": "direct_quote"}]},
                        "emotional_pattern": {}, "relationship_behavior": {}},
            "memory": {"core_facts": [{"id": "mi_A", "content": "她话少", "status": "active",
                                       "confidence": 0.8, "importance": 1,
                                       "source_type": "user_input"}],
                       "preferences": [], "timeline": [], "shared_experiences": [],
                       "conflicts": [], "happy_memories": [], "breakup": [],
                       "inside_jokes": [], "daily_patterns": []},
            "corrections": []}


def main():
    # 1) real key check
    if not os.environ.get("DEEPSEEK_API"):
        print("REAL_LLM_RUN = BLOCKED_BY_MISSING_CREDENTIALS")
        return 1
    os.environ.setdefault("OPENAI_API_KEY", os.environ["DEEPSEEK_API"])
    os.environ.setdefault("OPENAI_BASE_URL", "https://api.deepseek.com")
    adapter = make_real_adapter()

    base_dir = os.path.join(HERE, "stage59_e2e", "exes")
    os.makedirs(base_dir, exist_ok=True)
    run = {"run_id": "stage59_e2e_" + uuid.uuid4().hex[:10],
           "provider": "openai", "model": "deepseek-chat",
           "timestamp": "2026-09-05T00:00:00", "results": {}}

    # ---- E1: Ex creation ----
    seed = new_seed()
    slugA = "e2e_a"
    sd, on_disk, skill = e1_create_ex(seed, base_dir, slugA)
    run["results"]["E1"] = {
        "slug": slugA, "dir": sd,
        "persona_memory_is_canonical": json.dumps(on_disk, ensure_ascii=False, sort_keys=True)
        == json.dumps(seed, ensure_ascii=False, sort_keys=True),
        "skill_has_persona_facts": any(m in skill for m in ("小明", "话少", "哈哈哈哈")),
        "chat_py_exists": os.path.exists(os.path.join(sd, "chat.py")),
        "meta_exists": os.path.exists(os.path.join(sd, "meta.json")),
        "versions_dir": os.path.isdir(os.path.join(sd, "versions")),
    }
    print("E1 done:", run["results"]["E1"])

    # ---- E2: real multi-turn conversation (Session A) ----
    rt, pm_path = e2_runtime(sd, adapter)
    sid = None
    turns = ["在吗", "你觉得她话多话少？", "不对，她其实话痨，特别能说那种。"]
    conv = []
    for t in turns:
        r = rt.respond(t, session_id=sid)
        if sid is None:
            sid = r["session_update"]["session_id"]
        conv.append({"user": t, "assistant": r["assistant_response"],
                     "correction_result": r.get("correction_result")})
    run["results"]["E2"] = {"session_id": sid, "turns": conv}
    for i, c in enumerate(conv):
        print(f"\n[E2 turn {i}] U: {c['user']}\n  A: {c['assistant']}")
    # correction proposal produced?
    corr = conv[-1].get("correction_result")
    run["results"]["E3_proposal"] = corr
    print("\n[E3 proposal] correction_result:", json.dumps(corr, ensure_ascii=False))
    run["sd"] = sd
    run["pm_path"] = pm_path
    run["sid"] = sid
    out = os.path.join(HERE, "stage59_e2e", run["run_id"] + ".json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(run, f, ensure_ascii=False, indent=2)
    print("\nE1+E2 saved:", out)


if __name__ == "__main__":
    main()
