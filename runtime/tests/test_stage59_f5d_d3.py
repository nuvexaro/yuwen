#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 5.9-B / F5-d D3：retrieve/assess_support 使用 effective view 集成测试。

验证：
  - projected memory 能被 retrieve() 命中 / paraphrase 命中
  - assess_support() 对 projected correction 给正确状态
  - correction 当前轮不 self-project
  - 下一普通轮使用 projection
  - memory / relationship / shared projection 均 retrieve-able
  - persona zero leakage
  - 同一 correction 不重复投影
  - existing memory + projected correction 不产生双重事实/不误标 superseded
  - frozen PM bytes unchanged
  - A′ 五状态保持（空 memory→unsupported；无关 projection 不使 claim 变 supported，仍被拦）
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.dirname(HERE)
for p in (RUNTIME,):
    if p not in sys.path:
        sys.path.insert(0, p)

import reality_boundary as rb  # noqa: E402
import memory_retrieval as mr  # noqa: E402
import correction_runtime as cr  # noqa: E402
from persona_runtime import PersonaRuntime  # noqa: E402
from llm_gateway import LLMGateway  # noqa: E402


class C:
    ok_n = 0
    fail_n = 0
    fails = []

    @classmethod
    def ok(cls, name, cond, detail=""):
        if cond:
            cls.ok_n += 1
        else:
            cls.fail_n += 1
            cls.fails.append(name + (f" — {detail}" if detail else ""))
            print(f"FAIL {name} {detail}")


def empty_pm():
    return {"schema_version": "1.2", "persona": {
        "layer0_rules": {"do_not_say": [], "specific_edges": [], "reality_boundary": None},
        "identity": {"name_or_alias": {"claim_id": "pc_n", "value": "小明", "evidence_ids": [],
                                       "confidence": 1.0, "basis": "user_report_only"},
                     "relationship": {}},
        "speech_style": {"catchphrases": [], "examples": [], "punctuation": None, "tone": []},
        "emotional_pattern": {}, "relationship_behavior": {}},
        "memory": {k: [] for k in ("preferences", "timeline", "shared_experiences", "conflicts",
                                   "happy_memories", "breakup", "inside_jokes", "core_facts",
                                   "daily_patterns")}, "corrections": []}


def ov(domain, field, value, new_id, st="纠正", at="t1"):
    return {"target_domain": domain, "target_kind": "new_memory_item", "target_id": None,
            "old_value": None, "corrected_value": value, "new_claim_id": new_id,
            "field": field, "source_turn": st, "at": at}


def make_rt(pm):
    g = LLMGateway(adapter=lambda p, **k: "嗯 知道了。", model="mock")
    return PersonaRuntime(persona_memory=pm, gateway=g)


def main():
    print("=== Stage 5.9-B / F5-d D3: integration of effective view ===")
    now = datetime(2026, 9, 1)

    # ---- 1/2. retrieve hits projected + paraphrase ----
    pm = empty_pm()
    view = cr.effective_memory_view(pm, [ov("memory", "memory.core_facts", "特别话痨", "mi_cf")])
    r = mr.retrieve(view, {}, "她话多话少", k=5, now=now)
    C.ok("D3: retrieve hits projected correction", any(x["memory"]["id"] == "mi_cf" for x in r["items"]),
         str([x["memory"]["id"] for x in r["items"]]))
    r2 = mr.retrieve(view, {}, "她是不是话特别密", k=5, now=now)
    C.ok("D3: paraphrase hits projected", any(x["memory"]["id"] == "mi_cf" for x in r2["items"]),
         str([x["memory"]["id"] for x in r2["items"]]))

    # ---- 3. assess_support on related projected ----
    fl = rb.check_reality(view, "她话多话少？", now=now)
    rr = mr.retrieve(view, {}, "她话多话少？", k=5, now=now)
    sup = rb.assess_support(view, "她话多话少？", retrieved_items=rr["items"], now=now, flags=fl)
    C.ok("D3: assess_support related projected not blocked-unsupported",
         sup["boundary_state"] in ("supported", "ordinary"),
         f"state={sup['boundary_state']} active={sup.get('boundary_active')}")

    # ---- 4. correction turn: no self-project, boundary ordinary/inactive ----
    pm4 = empty_pm()
    rt4 = make_rt(pm4)
    r4 = rt4.respond("不对，她其实特别话痨。", session_id="s4")
    fl4 = r4["reality_flags"]
    C.ok("D3: correction-turn boundary not boundary-active (no self-project)",
         fl4.get("boundary_state") in ("ordinary", None) and fl4.get("boundary_active") in (False, None),
         str({k: fl4.get(k) for k in ("boundary_state", "boundary_active", "user_category")}))

    # ---- 5. next normal turn uses projection ----
    s = rt4.store.get("s4")
    C.ok("D3: overlay written after correction", s is not None and len(s.persona_overlay) >= 1)
    nid = s.persona_overlay[0]["new_claim_id"]
    # 普通轮 respond() 内部会用 effective view；这里手动验证 retrieve 命中
    view5 = cr.effective_memory_view(pm4, s.persona_overlay)
    r5 = mr.retrieve(view5, s.to_dict(), "她话多话少？", k=5, now=now)
    C.ok("D3: next-turn retrieve hits projected", any(x["memory"]["id"] == nid for x in r5["items"]),
         str([x["memory"]["id"] for x in r5["items"]]))

    # ---- 6. memory/relationship/shared all retrievable ----
    for domain, field, val, nid in (
            ("memory", "memory.core_facts", "话痨", "mi_a"),
            ("relationship_memory", "memory.relationship", "其实分手了", "mi_b"),
            ("shared_memory", "memory.shared_experiences", "没去过北京去天津", "mi_c")):
        v = cr.effective_memory_view(empty_pm(), [ov(domain, field, val, nid)])
        rr = mr.retrieve(v, {}, val, k=5, now=now)
        C.ok(f"D3: {domain} retrievable", any(x["memory"]["id"] == nid for x in rr["items"]),
             f"{domain}: {[x['memory']['id'] for x in rr['items']]}")

    # ---- 7. persona zero leakage ----
    v7 = cr.effective_memory_view(empty_pm(), [ov("persona", "persona.speech_style", "我话很少", "pc_x")])
    r7 = mr.retrieve(v7, {}, "我说话", k=5, now=now)
    C.ok("D3: persona zero leakage (retrieve empty)", r7["items"] == [], str(r7["items"]))

    # ---- 8. same correction not duplicated ----
    ov8 = [ov("memory", "memory.core_facts", "话痨", "mi_same")]
    v8a = cr.effective_memory_view(empty_pm(), ov8)
    v8b = cr.effective_memory_view(empty_pm(), ov8 + [dict(ov("memory", "memory.core_facts", "话痨", "mi_same"))])
    C.ok("D3: same correction not duplicated",
         [m["id"] for m in v8a["memory"]["core_facts"]].count("mi_same") == 1
         and [m["id"] for m in v8b["memory"]["core_facts"]].count("mi_same") == 1)

    # ---- 9. existing memory + projected correction coexist, real not mis-superseded ----
    pm9 = empty_pm()
    pm9["memory"]["core_facts"] = [{"id": "mi_real", "content": "她以前话很少", "status": "active",
                                    "confidence": 0.8, "importance": 1, "source_type": "user_input"}]
    v9 = cr.effective_memory_view(pm9, [ov("memory", "memory.core_facts", "特别话痨", "mi_new")])
    cf9 = [m["id"] for m in v9["memory"]["core_facts"]]
    C.ok("D3: existing + projected coexist", "mi_real" in cf9 and "mi_new" in cf9, str(cf9))
    real9 = next(m for m in v9["memory"]["core_facts"] if m["id"] == "mi_real")
    C.ok("D3: existing real not superseded by projection", real9["status"] == "active", str(real9["status"]))

    # ---- 10. frozen bytes unchanged ----
    pm10 = empty_pm()
    b10 = json.dumps(pm10, ensure_ascii=False, sort_keys=True)
    cr.effective_memory_view(pm10, [ov("memory", "memory.core_facts", "话痨", "mi_x")])
    C.ok("D3: frozen bytes unchanged", json.dumps(pm10, ensure_ascii=False, sort_keys=True) == b10)

    # ---- 11. A′ preserved: unrelated projection does not flip empty-memory claim to supported ----
    pm11 = empty_pm()
    fl_a = rb.check_reality(pm11, "我们去年去过上海，对吧？", now=now)
    sup_a = rb.assess_support(pm11, "我们去年去过上海，对吧？", retrieved_items=[], now=now, flags=fl_a)
    C.ok("D3/A': no-overlay empty still unsupported_claim", sup_a["boundary_state"] == "unsupported_claim",
         str(sup_a["boundary_state"]))
    v11 = cr.effective_memory_view(pm11, [ov("memory", "memory.core_facts", "话痨", "mi_cf")])
    fl_b = rb.check_reality(v11, "我们去年去过上海，对吧？", now=now)
    rr_b = mr.retrieve(v11, {}, "我们去年去过上海，对吧？", k=5, now=now)
    sup_b = rb.assess_support(v11, "我们去年去过上海，对吧？", retrieved_items=rr_b["items"], now=now, flags=fl_b)
    C.ok("D3/A': unrelated projection does NOT make claim supported",
         sup_b["boundary_state"] in ("insufficient_evidence", "unsupported_claim"),
         str(sup_b["boundary_state"]))
    C.ok("D3/A': unrelated projection stays boundary_active",
         sup_b.get("boundary_active") is True, str(sup_b.get("boundary_active")))

    print(f"\n通过 {C.ok_n} / 失败 {C.fail_n}")
    for f in C.fails:
        print("  -", f)
    sys.exit(0 if C.fail_n == 0 else 1)


if __name__ == "__main__":
    main()
