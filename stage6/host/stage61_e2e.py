#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 6.1 Real E2E — real Host + real DeepSeek + real operator confirmation.

验证 16 步全链。用真实 Host skeleton（production_host.Host）+ real_llm_adapter。
correction confirm 停在 proposal 处请 operator 确认。结果写 stage6/e2e_results/。
Mock 不作为 Real E2E 证据（若出现 fallback 记录 error==gateway_fallback，不当作成功）。
"""

from __future__ import annotations

import json
import os
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for p in (os.path.join(ROOT, "runtime"), os.path.join(ROOT, "tools"),
          os.path.join(ROOT, "benchmark"), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from production_host import Host  # noqa: E402


def make_real_adapter():
    import real_llm_adapter as rla
    return rla.make_provider_adapter("openai")


def seed_pm(name, core_content):
    import skill_writer_v12 as sw12  # noqa: F401  (skill_writer used below)
    return {"schema_version": "1.2", "revision": 1,
            "persona": {"layer0_rules": {"do_not_say": [], "specific_edges": [], "reality_boundary": None},
                        "identity": {"name_or_alias": {"claim_id": "pc_n", "value": name, "evidence_ids": ["c1"],
                                                       "confidence": 1.0, "basis": "user_report_only"},
                                     "relationship": {}},
                        "speech_style": {"catchphrases": [{"claim_id": "pc_c", "value": "哈哈哈哈", "evidence_ids": ["c1"],
                                                           "confidence": 0.9, "basis": "direct_quote"}],
                                         "examples": [], "punctuation": None,
                                         "tone": [{"claim_id": "pc_t", "value": "简短冷淡", "evidence_ids": ["c1"],
                                                   "confidence": 0.9, "basis": "direct_quote"}]},
                        "emotional_pattern": {}, "relationship_behavior": {}},
            "memory": {"core_facts": [{"id": "mi_A", "content": core_content, "status": "active",
                                       "confidence": 0.8, "importance": 1,
                                       "source_type": "user_input"}],
                       "preferences": [], "timeline": [], "shared_experiences": [],
                       "conflicts": [], "happy_memories": [], "breakup": [],
                       "inside_jokes": [], "daily_patterns": []},
            "corrections": []}


def main():
    if not os.environ.get("DEEPSEEK_API"):
        print("REAL_LLM_RUN = BLOCKED_BY_MISSING_CREDENTIALS")
        return 1
    os.environ.setdefault("OPENAI_API_KEY", os.environ["DEEPSEEK_API"])
    os.environ.setdefault("OPENAI_BASE_URL", "https://api.deepseek.com")
    adapter = make_real_adapter()

    out_dir = os.path.join(HERE, "e2e_results")
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.join(out_dir, "exes")
    ev = {"run_id": "stage61_e2e_" + uuid.uuid4().hex[:10],
          "provider": "openai", "model": "deepseek-chat",
          "steps": {}, "real_api_calls": 0}

    # ---- step 1-2: Create Ex A + persona_memory.json ----
    import skill_writer_v12 as sw12
    sdA = sw12.init_ex_instance(seed_pm("小明", "她话少"), base, "ex_a")
    pmA0 = json.load(open(os.path.join(sdA, "persona_memory.json"), encoding="utf-8"))
    ev["steps"]["E1_create"] = {"canonical_revision": pmA0.get("revision"), "exists": os.path.exists(sdA)}

    # ---- step 3-4: Host create session A, real DeepSeek multi-turn ----
    host = Host(base, adapter=adapter, model="deepseek-chat",
                session_store_dir=os.path.join(out_dir, "sessions"))
    sidA = host.new_session("ex_a")
    ev["steps"]["E2_sessionA"] = {"session_id": sidA, "slug": host.session_slug(sidA)}
    # 3 turns: establish, then probe the (wrong) memory fact, then user corrects
    turns = ["在吗", "你觉得她话多话少？", "不对，她其实话痨，特别能说那种。"]
    conv = []
    for t in turns:
        out = host.respond(sidA, t)
        ev["real_api_calls"] += 1
        conv.append({"user": t, "assistant": out["assistant_response"],
                     "error": out.get("error"), "correction_result": out.get("correction_result")})
        # fallback 不得当作真实成功
        if out.get("error") == "gateway_fallback":
            print("FALLBACK OCCURRED (not counted as real success) at:", t)
    ev["steps"]["E3_multiturn"] = conv
    for c in conv:
        print(f"\n[U] {c['user']}\n[A] {c['assistant']}")
        if c.get("error"): print("  error:", c["error"])
    # step 5-7: correction proposal
    props = host.pending_proposals(sidA)
    ev["steps"]["E4_proposal"] = props
    print("\n[proposal]", json.dumps(props, ensure_ascii=False))
    ev["sidA"] = sidA
    ev["sdA"] = sdA
    ev["host_dir"] = out_dir
    json.dump(ev, open(os.path.join(out_dir, ev["run_id"] + ".json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("\nStage 6.1 E2E step1-7 saved:", ev["run_id"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
