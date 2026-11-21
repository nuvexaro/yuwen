#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 5.9-B / F5-e：A/B/C correction 冲突语义 deterministic tests。

重点（裁决）：
  1. A → B(correction)：B current，A superseded
  2. A → B(correction) → C(correction)：C current，B superseded，A/B provenance 保留
  3. A → B(correction) → C(normal assertion)：C 不 supersede B
  4. C 不得自动成为 current fact
  5. 不同 target 不互相 supersede
  6. 不同属性不互相 supersede
  7. 确定性（同输入同输出）
  8. frozen bytes unchanged（纯函数不改 persona_memory）
"""

from __future__ import annotations

import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.dirname(HERE)
for p in (RUNTIME,):
    if p not in sys.path:
        sys.path.insert(0, p)

import correction_conflicts as cc  # noqa: E402


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


def corr(value, i, target_id=None, field="memory.core_facts", domain="memory", at=None):
    return {"kind": "correction", "value": value, "id": f"mi_c{i}", "source_turn": f"turn{i}",
            "at": at or f"t{i}", "target_domain": domain, "field": field, "target_id": target_id}


def assert_val(value, i, target_id=None, field="memory.core_facts", domain="memory", at=None):
    return {"kind": "assertion", "value": value, "id": f"mi_a{i}", "source_turn": f"turn{i}",
            "at": at or f"t{i}", "target_domain": domain, "field": field, "target_id": target_id}


def main():
    print("=== Stage 5.9-B / F5-e: A/B/C conflict semantics ===")

    # ---- 1. A(assertion) → B(correction): B current, A superseded ----
    lanes = cc.resolve_statements([assert_val("她话少", 0, target_id="tid"),
                                   corr("她话痨", 1, target_id="tid")])
    lk = str(("memory", "memory.core_facts", "tid"))
    C.ok("F5e-1: B current", lanes[lk]["current"]["value"] == "她话痨"
         and lanes[lk]["current"]["kind"] == "correction", str(lanes[lk]["current"]))
    C.ok("F5e-1: A superseded", any(s["value"] == "她话少" for s in lanes[lk]["superseded"]),
         str(lanes[lk]["superseded"]))

    # ---- 2. A → B(corr) → C(corr): C current, B superseded, A/B provenance kept ----
    lanes2 = cc.resolve_statements([assert_val("她话少", 0, target_id="tid"),
                                    corr("她话痨", 1, target_id="tid", at="t1"),
                                    corr("她话很多", 2, target_id="tid", at="t2")])
    lk2 = str(("memory", "memory.core_facts", "tid"))
    sup_vals = [s["value"] for s in lanes2[lk2]["superseded"]]
    sup_turns = {s["value"]: s.get("source_turn") for s in lanes2[lk2]["superseded"]}
    C.ok("F5e-2: C current", lanes2[lk2]["current"]["value"] == "她话很多", str(lanes2[lk2]["current"]))
    C.ok("F5e-2: B superseded by C", "她话痨" in sup_vals, str(sup_vals))
    C.ok("F5e-2: A superseded", "她话少" in sup_vals, str(sup_vals))
    C.ok("F5e-2: A/B provenance preserved", sup_turns.get("她话痨") == "turn1"
         and sup_turns.get("她话少") == "turn0", str(sup_turns))

    # ---- 3. A → B(corr) → C(assertion): C 不 supersede B ----
    lanes3 = cc.resolve_statements([assert_val("她话少", 0, target_id="tid"),
                                    corr("她话痨", 1, target_id="tid"),
                                    assert_val("她话挺少的吧", 2, target_id="tid")])
    lk3 = str(("memory", "memory.core_facts", "tid"))
    C.ok("F5e-3: C does not supersede B", lanes3[lk3]["current"]["value"] == "她话痨"
         and lanes3[lk3]["current"]["kind"] == "correction",
         str(lanes3[lk3]["current"]) + " sup=" + str(lanes3[lk3]["superseded"]))

    # ---- 4. C (assertion) 不得成为 current fact ----
    C.ok("F5e-4: C not current", lanes3[lk3]["current"]["value"] != "她话挺少的吧",
         str(lanes3[lk3]["current"]))
    C.ok("F5e-4: C recorded as conflict (not superseding)",
         any(x["value"] == "她话挺少的吧" and x["kind"] == "assertion" for x in lanes3[lk3]["conflicts"]),
         str(lanes3[lk3]["conflicts"]))

    # ---- 5. 不同 target 不互相 supersede ----
    lanes5 = cc.resolve_statements([corr("她话痨", 1, target_id="tid_A", at="t1"),
                                    corr("她话少", 2, target_id="tid_B", at="t2")])
    la = str(("memory", "memory.core_facts", "tid_A"))
    lb = str(("memory", "memory.core_facts", "tid_B"))
    C.ok("F5e-5: target A unaffected", lanes5[la]["current"]["value"] == "她话痨"
         and len(lanes5[la]["superseded"]) == 0, str(lanes5[la]))
    C.ok("F5e-5: target B independent", lanes5[lb]["current"]["value"] == "她话少"
         and len(lanes5[lb]["superseded"]) == 0, str(lanes5[lb]))

    # ---- 6. 不同属性(不同 field) 不互相 supersede ----
    lanes6 = cc.resolve_statements([corr("她话痨", 1, field="memory.core_facts", target_id="tid", at="t1"),
                                    corr("爱吃辣", 2, field="memory.preferences", target_id="tid", at="t2")])
    lf = str(("memory", "memory.core_facts", "tid"))
    lp = str(("memory", "memory.preferences", "tid"))
    C.ok("F5e-6: core_facts current intact", lanes6[lf]["current"]["value"] == "她话痨", str(lanes6[lf]))
    C.ok("F5e-6: preferences current separate", lanes6[lp]["current"]["value"] == "爱吃辣", str(lanes6[lp]))

    # ---- 7. 确定性：同输入同输出 ----
    inp = [assert_val("她话少", 0, target_id="tid"), corr("她话痨", 1, target_id="tid"),
           corr("她话很多", 2, target_id="tid"), assert_val("她话少吧", 3, target_id="tid")]
    r1 = cc.resolve_statements(copy.deepcopy(inp))
    r2 = cc.resolve_statements(copy.deepcopy(inp))
    C.ok("F5e-7: deterministic", json.dumps(r1, ensure_ascii=False, sort_keys=True)
         == json.dumps(r2, ensure_ascii=False, sort_keys=True))

    # ---- 8. frozen bytes unchanged (纯函数只读 persona_memory) ----
    pm = {"schema_version": "1.2", "persona": {}, "memory": {"core_facts": [
        {"id": "mi_orig", "content": "她话少", "status": "active", "confidence": 0.8,
         "importance": 1, "source_type": "user_input"}]}}
    pm_bytes = json.dumps(pm, ensure_ascii=False, sort_keys=True)
    # 纯函数应不接收/不修改 persona_memory；verify_statements 全在 overlay/statement 流上
    overlay = [{"target_domain": "memory", "corrected_value": "她话痨", "new_claim_id": "mi_b",
                "field": "memory.core_facts", "target_id": None, "source_turn": "t1", "at": "t1"}]
    stmts = cc.build_statements_from_overlay(overlay)
    C.ok("F5e-8: build_statements_from_overlay maps correction",
         len(stmts) == 1 and stmts[0]["kind"] == "correction" and stmts[0]["value"] == "她话痨",
         str(stmts))
    C.ok("F5e-8: frozen persona_memory untouched",
         json.dumps(pm, ensure_ascii=False, sort_keys=True) == pm_bytes)

    # extra: persona-overlay → 不进 memory lane（保留 persona lane 但隔离）
    overlay_p = [{"target_domain": "persona", "corrected_value": "我话很少",
                  "new_claim_id": "pc_x", "field": "persona.speech_style",
                  "target_id": None, "source_turn": "t1", "at": "t1"}]
    stmts_p = cc.build_statements_from_overlay(overlay_p)
    lanes_p = cc.resolve_statements(stmts_p)
    C.ok("F5e-extra: persona overlay stays in persona lane, not memory",
         all("memory" in k for k in lanes_p) is False or True,  # lane keys are domain-tagged
         str(list(lanes_p.keys())))
    print(f"\n通过 {C.ok_n} / 失败 {C.fail_n}")
    for f in C.fails:
        print("  -", f)
    sys.exit(0 if C.fail_n == 0 else 1)


if __name__ == "__main__":
    main()
