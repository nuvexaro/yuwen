#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Real E2E E4-E6 driver：persist_confirmed → canonical；cross-session；isolation。

E4  Persistence：把 E3 已确认的 correction persist_confirmed → persona_memory.json
E5  Cross-session：Session B 从更新后 canonical 重载 → 真实 LLM 采用新信息
E6  Instance isolation：Ex-B 独立；correction 不串 instance

真实 LLM（real_llm_adapter + DEEPSEEK_API）。不 mock。
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "runtime"), os.path.join(ROOT, "tools"), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)


def main():
    if not os.environ.get("DEEPSEEK_API"):
        print("BLOCKED_BY_MISSING_CREDENTIALS")
        return 1
    os.environ.setdefault("OPENAI_API_KEY", os.environ["DEEPSEEK_API"])
    os.environ.setdefault("OPENAI_BASE_URL", "https://api.deepseek.com")
    import real_llm_adapter as rla
    adapter = rla.make_provider_adapter("openai")

    # 定位最新 E1+E2 run 产物
    e2e_dir = os.path.join(HERE, "stage59_e2e")
    runfiles = sorted([f for f in os.listdir(e2e_dir) if f.startswith("stage59_e2e_") and f.endswith(".json")])
    runf = os.path.join(e2e_dir, runfiles[-1])
    r1 = json.load(open(runf, encoding="utf-8"))
    sd = r1["sd"]; pm_path = r1["pm_path"]
    corr = r1["results"]["E3_proposal"]
    print("E2 run:", r1["run_id"])

    # ---- E4: persist_confirmed（confirmed correction → canonical）----
    confirmed = [{"id": corr["new_claim_id"], "corrected_value": "她话痨，特别能说那种",
                  "target_id": corr["old_claim_id"], "target_path": "memory.core_facts",
                  "user_statement": "不对，她其实话痨，特别能说那种。", "created_at": "2026-09-05T00:00:00"}]
    sys.path.insert(0, sd)
    from chat import persist_confirmed
    before = json.load(open(pm_path, encoding="utf-8"))
    res = persist_confirmed(pm_path, confirmed, backup_dir=os.path.join(sd, "versions"))
    after = json.load(open(pm_path, encoding="utf-8"))
    print("\n[E4] persist result:", res)
    print("[E4] corrections after:", [(c["id"], c["status"], c.get("superseded_by")) for c in after["corrections"]])
    print("[E4] memory mi_A status:", [ (m["id"], m["status"]) for m in after["memory"]["core_facts"] ])

    # ---- E5: Cross-session - Session B from updated canonical ----
    import sys as _s
    _s.path.insert(0, sd)
    from chat import load_instance, make_runtime
    baseB, _ = load_instance(pm_path)   # reload updated canonical
    rtB = make_runtime(baseB, adapter=adapter, model="deepseek-chat")
    sidB = None
    convB = []
    for t in ["在吗", "她话多话少？", "她是不是其实话特别少？"]:
        rr = rtB.respond(t, session_id=sidB)
        if sidB is None:
            sidB = rr["session_update"]["session_id"]
        convB.append({"user": t, "assistant": rr["assistant_response"],
                      "used_memory": rr["used"].get("memory_items", [])})
    print("\n[E5] Session B (from updated canonical):")
    for i, c in enumerate(convB):
        print(f"  U: {c['user']}\n  A: {c['assistant']}  used={c['used_memory']}")

    # ---- E6: Instance isolation - Ex-B separate ----
    from skill_writer_v12 import init_ex_instance
    def new_seed():
        return {"schema_version": "1.2", "revision": 1,
                "persona": {"layer0_rules": {}, "identity": {"name_or_alias": {"value": "阿B", "claim_id": "pc_b"}}},
                "memory": {"core_facts": [{"id": "mi_other", "content": "她爱猫", "status": "active",
                                           "confidence": 0.8, "importance": 1, "source_type": "user_input"}],
                           "preferences": [], "timeline": [], "shared_experiences": [],
                           "conflicts": [], "happy_memories": [], "breakup": [],
                           "inside_jokes": [], "daily_patterns": []}, "corrections": []}
    baseBdir = os.path.join(e2e_dir, "exes")
    sdB = init_ex_instance(new_seed(), baseBdir, "e2e_b")
    pmB = json.load(open(os.path.join(sdB, "persona_memory.json"), encoding="utf-8"))
    # correction 不串：Ex-A 的 corr 不应出现在 Ex-B
    leaked = any(c["id"] == corr["new_claim_id"] for c in pmB["corrections"])
    print("\n[E6] Ex-B persona_memory.json corrections:", pmB["corrections"])
    print("[E6] Ex-A corr leaked into Ex-B?", leaked)
    print("[E6] Ex-A final canonical corrections:", [(c["id"], c["status"]) for c in after["corrections"]])

    out = os.path.join(e2e_dir, r1["run_id"].replace("stage59_e2e_", "stage59_e2e_persist_") + ".json")
    json.dump({"E4": {"before_corrections": before["corrections"], "after_corrections": after["corrections"]},
               "E5": {"session_B": sidB, "turns": convB},
               "E6": {"exB_corrections": pmB["corrections"], "exA_leaked_into_B": leaked}},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("\nE4+E5+E6 saved:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
