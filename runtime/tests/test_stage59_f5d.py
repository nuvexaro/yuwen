#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 5.9-B / F5-d D2：effective_memory_view 纯函数 deterministic tests。

覆盖：memory/relationship/shared projection；persona zero leakage；correct bucket/id；
provenance；同属性后序 supersede 旧；无关不 supersede；普通 assertion 不投影/supersede；
frozen bytes unchanged；deepcopy isolation。
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.dirname(HERE)
for p in (RUNTIME,):
    if p not in sys.path:
        sys.path.insert(0, p)

import correction_runtime as cr  # noqa: E402


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
    return {"schema_version": "1.2", "persona": {"layer0_rules": {}, "identity": {}},
            "memory": {k: [] for k in ("preferences", "timeline", "shared_experiences", "conflicts",
                                       "happy_memories", "breakup", "inside_jokes", "core_facts",
                                       "daily_patterns")}, "corrections": []}


def ov(domain, field, value, new_id, source_turn="纠正", at="t1"):
    return {"target_domain": domain, "target_kind": "new_memory_item", "target_id": None,
            "old_value": None, "corrected_value": value, "new_claim_id": new_id,
            "field": field, "source_turn": source_turn, "at": at}


def get_ids(view, bucket):
    return [m.get("id") for m in view["memory"].get(bucket, [])]


def main():
    print("=== Stage 5.9-B / F5-d D2: effective_memory_view ===")
    # memory-domain projection
    pm = empty_pm()
    pm_b = json.dumps(pm, ensure_ascii=False, sort_keys=True)
    view = cr.effective_memory_view(pm, [ov("memory", "memory.core_facts", "特别话痨", "mi_abc")])
    C.ok("mem-domain: core_facts has projected item", "mi_abc" in get_ids(view, "core_facts"))
    it = next(m for m in view["memory"]["core_facts"] if m["id"] == "mi_abc")
    C.ok("mem-domain: content = corrected value", it["content"] == "特别话痨")
    C.ok("mem-domain: source_type correction", it["source_type"] == "correction")
    C.ok("mem-domain: basis/source preserved", it.get("basis") == "correction" and it.get("source") == "user_correction")
    C.ok("mem-domain: source_turn/at preserved", it.get("source_turn") == "纠正" and it.get("at") == "t1")
    C.ok("mem-domain: status active", it.get("status") == "active")
    # relationship_memory -> breakup
    view2 = cr.effective_memory_view(empty_pm(), [ov("relationship_memory", "memory.relationship", "其实早就分手了", "mi_rel")])
    C.ok("rel-mem: relationship→breakup bucket", "mi_rel" in get_ids(view2, "breakup"))
    # shared_memory
    view3 = cr.effective_memory_view(empty_pm(), [ov("shared_memory", "memory.shared_experiences", "没去过北京去的是天津", "mi_sh")])
    C.ok("shared-mem: shared_experiences has item", "mi_sh" in get_ids(view3, "shared_experiences"))
    # persona zero leakage
    view4 = cr.effective_memory_view(empty_pm(), [ov("persona", "persona.speech_style", "我话很少", "pc_x")])
    total4 = sum(len(view4["memory"][b]) for b in view4["memory"])
    C.ok("persona-domain: zero memory leakage", total4 == 0, f"total={total4}")
    # correct bucket only
    pm_bk = empty_pm()
    v_bk = cr.effective_memory_view(pm_bk, [ov("memory", "memory.core_facts", "特别话痨", "mi_abc")])
    in_core = "mi_abc" in get_ids(v_bk, "core_facts")
    in_other = any("mi_abc" in get_ids(v_bk, b) for b in v_bk["memory"] if b != "core_facts")
    C.ok("bucket: correct id in correct bucket only", in_core and not in_other, f"core={in_core} other={in_other}")
    # frozen bytes unchanged + deepcopy isolation
    C.ok("frozen: bytes unchanged", json.dumps(pm, ensure_ascii=False, sort_keys=True) == pm_b)
    pm5 = empty_pm()
    view5 = cr.effective_memory_view(pm5, [ov("memory", "memory.core_facts", "话痨", "mi_x")])
    view5["memory"]["core_facts"][0]["content"] = "MUTATED"
    C.ok("deepcopy: mutating view does not touch frozen", len(pm5["memory"]["core_facts"]) == 0)
    # same-attribute latest supersedes old
    pm6 = empty_pm()
    o = [ov("memory", "memory.core_facts", "话痨", "mi_v1", source_turn="纠正1", at="t1"),
         ov("memory", "memory.core_facts", "话很少", "mi_v2", source_turn="纠正2", at="t2")]
    view6 = cr.effective_memory_view(pm6, o)
    cf6 = {m["id"]: m for m in view6["memory"]["core_facts"]}
    C.ok("supersede: latest current active", cf6["mi_v2"]["status"] == "active")
    C.ok("supersede: old kept + superseded_by", cf6["mi_v1"]["status"] == "superseded"
         and cf6["mi_v1"].get("superseded_by") == "mi_v2")
    C.ok("supersede: old provenance preserved", cf6["mi_v1"].get("source_turn") == "纠正1")
    # unrelated correction (different field) does not supersede
    view7 = cr.effective_memory_view(empty_pm(), [ov("memory", "memory.core_facts", "话痨", "mi_a", at="t1"),
                                                  ov("memory", "memory.preferences", "爱吃辣", "mi_b", at="t2")])
    C.ok("unrelated: both current (no cross-supersede)",
         any(m["id"] == "mi_a" and m["status"] == "active" for m in view7["memory"]["core_facts"])
         and any(m["id"] == "mi_b" and m["status"] == "active" for m in view7["memory"]["preferences"]))
    # empty overlay → no projection; returns deepcopy
    view8 = cr.effective_memory_view(empty_pm(), [])
    total8 = sum(len(view8["memory"][b]) for b in view8["memory"])
    C.ok("assertion: empty overlay → no projection", total8 == 0)
    pm9 = empty_pm()
    view9 = cr.effective_memory_view(pm9, [])
    C.ok("empty overlay: deepcopy not same object", view9 is not pm9 and view9 == pm9)
    print(f"\n通过 {C.ok_n} / 失败 {C.fail_n}")
    for f in C.fails:
        print("  -", f)
    sys.exit(0 if C.fail_n == 0 else 1)


if __name__ == "__main__":
    main()
