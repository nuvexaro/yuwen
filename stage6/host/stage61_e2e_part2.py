#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 6.1 Real E2E part2：confirm → persist → new session → adopt/resist → Ex-B isolation."""

from __future__ import annotations

import json
import os
import sys
import glob

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for p in (os.path.join(ROOT, "runtime"), os.path.join(ROOT, "tools"),
          os.path.join(ROOT, "benchmark"), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from production_host import Host  # noqa: E402


def main():
    if not os.environ.get("DEEPSEEK_API"):
        print("BLOCKED_BY_MISSING_CREDENTIALS")
        return 1
    os.environ.setdefault("OPENAI_API_KEY", os.environ["DEEPSEEK_API"])
    os.environ.setdefault("OPENAI_BASE_URL", "https://api.deepseek.com")
    import real_llm_adapter as rla
    adapter = rla.make_provider_adapter("openai")

    out_dir = os.path.join(HERE, "e2e_results")
    base = os.path.join(out_dir, "exes")
    # load latest step1-7 result
    runs = sorted(glob.glob(os.path.join(out_dir, "stage61_e2e_*.json")))
    runf = runs[-1]
    ev = json.load(open(runf, encoding="utf-8"))
    sidA = ev["sidA"]; sdA = ev["sdA"]
    props = ev["steps"]["E4_proposal"]
    pid = props[0]["proposal_id"]
    print("resume:", ev["run_id"], "session", sidA)

    host = Host(base, adapter=adapter, model="deepseek-chat",
                session_store_dir=os.path.join(out_dir, "sessions"))
    # 重启场景：把 file-backed 的 sidA 重新 attach 到该 Host（session 恢复）
    host.attach_session("ex_a", sidA)
    print("attached session:", sidA)

    # step 9-10: confirm + persist
    res = host.confirm_proposal(sidA, pid)
    ev["steps"]["E5_confirm_persist"] = res
    print("\n[confirm/persist]", json.dumps(res, ensure_ascii=False))
    pmA = json.load(open(os.path.join(sdA, "persona_memory.json"), encoding="utf-8"))
    ev["steps"]["E6_canonical_after"] = {
        "revision": pmA.get("revision"),
        "corrections": [(c["id"], c["status"], c.get("superseded_by")) for c in pmA["corrections"]],
        "mi_A": [ (m["id"], m["status"]) for m in pmA["memory"]["core_facts"] ],
    }
    print("[canonical after]", ev["steps"]["E6_canonical_after"])

    # step 11-13: new session B reload canonical, adopt
    sidB = host.new_session("ex_a")
    ev["steps"]["E7_sessionB"] = {"session_id": sidB}
    adopt_conv = []
    for t in ["在吗", "她话多话少？"]:
        out = host.respond(sidB, t)
        adopt_conv.append({"user": t, "assistant": out["assistant_response"],
                           "error": out.get("error")})
    ev["steps"]["E8_adoption"] = adopt_conv
    for c in adopt_conv:
        print(f"\n[SessionB U] {c['user']}\n[SessionB A] {c['assistant']}")

    # step 14: old-info resistance
    outR = host.respond(sidB, "她是不是其实话特别少？")
    ev["steps"]["E9_resist"] = {"user": "她是不是其实话特别少？",
                                "assistant": outR["assistant_response"], "error": outR.get("error")}
    print(f"\n[resist U] 她是不是其实话特别少？\n[resist A] {outR['assistant_response']}")

    # step 15-16: Ex-B isolation
    import skill_writer_v12 as sw12
    sdB = sw12.init_ex_instance(
        {"schema_version": "1.2", "revision": 1,
         "persona": {"layer0_rules": {}, "identity": {"name_or_alias": {"value": "阿B", "claim_id": "pc_b"}}},
         "memory": {"core_facts": [{"id": "mi_other", "content": "她爱猫", "status": "active",
                                    "confidence": 0.8, "importance": 1, "source_type": "user_input"}],
                    "preferences": [], "timeline": [], "shared_experiences": [], "conflicts": [],
                    "happy_memories": [], "breakup": [], "inside_jokes": [], "daily_patterns": []},
         "corrections": []}, base, "ex_b")
    pmB = json.load(open(os.path.join(sdB, "persona_memory.json"), encoding="utf-8"))
    leaked = any(c.get("id", "").startswith("mi_c674") for c in pmB["corrections"])
    ev["steps"]["E10_isolation"] = {"exB_corrections": pmB["corrections"],
                                    "exA_corr_leaked_into_B": leaked}
    print("\n[Ex-B corrections]", pmB["corrections"])
    print("[Ex-A leaked into Ex-B]", leaked)

    out = os.path.join(out_dir, ev["run_id"] + "_full.json")
    json.dump(ev, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("\nFULL E2E saved:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
