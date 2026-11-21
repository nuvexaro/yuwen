#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 5.9-B / F5-f Phase 3B：Persona Loader（verdict execution）deterministic tests。

覆盖裁决 16 项：
 1 B correction + C correction → C current / B superseded
 2 B projection 被准确识别为 F5-e 判 superseded 的 entity
 3 runtime 最终 active correction count = 1
 4 C correction 正常进入现有 F5-d overlay
 5 C.target_id == mi_A
 6 B/C 同 semantic lane
 7 ordinary assertion 不得 supersede B/C correction
 8 不同 field 不得互相 suppression
 9 多候选 unresolved 不得强行合并
10 rejected/superseded correction 不得重新激活
11 persona correction 不进入 memory lane
12 new Session 可以看到 long-term active correction
13 PM 原始 bytes 不变
14 Phase 2 SHA 不变（外部验证）
15 F5-d/F5-e SHA 不变（外部验证）
16 517/517、9/9（外部验证）
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

import correction_conflicts as f5e  # noqa: E402
import correction_longterm_projection as phase2  # noqa: E402
import correction_runtime as f5d  # noqa: E402
from persona_loader import (load_runtime_persona, correction_item_to_statement,  # noqa: E402
                            overlay_to_statement)


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


def longterm_pm(corrections, core_mem=None):
    if core_mem is None:
        core_mem = [{"id": "mi_A", "content": "她话少", "status": "superseded",
                     "confidence": 0.8, "importance": 1, "source_type": "user_input"}]
    pm = {"schema_version": "1.2", "persona": {"layer0_rules": {}, "identity": {}},
          "memory": {"core_facts": core_mem,
                     "preferences": [], "timeline": [], "shared_experiences": [],
                     "conflicts": [], "happy_memories": [], "breakup": [],
                     "inside_jokes": [], "daily_patterns": []},
          "corrections": corrections}
    return pm


def corr(cid, target_id, status="active", field="memory.core_facts", corrected_value="她话痨",
         target_kind="memory_item"):
    return {"id": cid, "target_kind": target_kind, "target_id": target_id,
            "target_path": field, "corrected_value": corrected_value,
            "user_statement": "纠正", "status": status}


def overlay(domain, field, value, nid, target_id=None, at="t9"):
    return {"target_domain": domain, "field": field, "target_id": target_id,
            "corrected_value": value, "new_claim_id": nid, "source_turn": "用户纠正", "at": at}


def active_items(pm):
    return [it for it in pm.get("memory", {}).get("core_facts", []) if it.get("status") == "active"]


def main():
    print("=== Stage 5.9-B / F5-f Phase 3B: persona loader ===")

    # ---- 1/2/3/4/5/6: B + C → C current, B superseded, active count=1 ----
    pm = longterm_pm([corr("corr_B", "mi_A")])
    C_ov = overlay("memory", "memory.core_facts", "她话特别多", "mi_C", target_id="mi_A")
    # F5-e verdict
    lanes = f5e.resolve_statements([correction_item_to_statement(pm["corrections"][0]),
                                    overlay_to_statement(C_ov)])
    lk = str(("memory", "memory.core_facts", "mi_A"))
    C.ok("1: F5-e says C current / B superseded", lanes[lk]["current"]["id"] == "mi_C"
         and any(s["id"] == "corr_B" for s in lanes[lk]["superseded"]), str(lanes[lk]))
    # loader + F5-d
    base = load_runtime_persona(pm, [C_ov])
    final = f5d.effective_memory_view(base, [C_ov])
    act = active_items(final)
    C.ok("2: B projection omitted from transient base",
         all(it.get("correction_id") != "corr_B" for it in base["memory"]["core_facts"]))
    C.ok("3: final active count == 1", len(act) == 1 and act[0]["content"] == "她话特别多",
         str([(a["content"], a["id"]) for a in act]))
    C.ok("4: C entered F5-d overlay (mi_C active)", any(a["id"] == "mi_C" for a in act), str(act))
    C.ok("5: C.target_id == mi_A", C_ov["target_id"] == "mi_A")
    C.ok("6: B/C same semantic lane",
         correction_item_to_statement(pm["corrections"][0]).get("target_id")
         == overlay_to_statement(C_ov).get("target_id") == "mi_A")

    # ---- 7: ordinary assertion must NOT supersede correction ----
    #   assertion 不是 correction → 不进 loader 的 correction 归约；走 F5-e assertion 规则进 conflict
    pm7 = longterm_pm([corr("corr_B", "mi_A")])
    B_stmt = correction_item_to_statement(pm7["corrections"][0])
    Asrt = {"kind": "assertion", "value": "她其实不怎么说话", "id": "mi_assert", "at": "t10",
            "target_domain": "memory", "field": "memory.core_facts", "target_id": "mi_A",
            "source_turn": "用户随口"}
    lanes7 = f5e.resolve_statements([B_stmt, Asrt])
    lk7 = str(("memory", "memory.core_facts", "mi_A"))
    C.ok("7: assertion not supersede correction", lanes7[lk7]["current"]["id"] == "corr_B"
         and any(x["value"] == "她其实不怎么说话" for x in lanes7[lk7]["conflicts"]), str(lanes7[lk7]))

    # ---- 8: different field no cross-suppression ----
    pm8 = longterm_pm([corr("corr_B", "mi_A", field="memory.core_facts"),
                       corr("corr_P", "mi_pref", field="memory.preferences", corrected_value="爱吃辣")])
    C8 = overlay("memory", "memory.preferences", "吃辣", "mi_Cpref", target_id="mi_pref", at="t9")
    base8 = load_runtime_persona(pm8, [C8])
    # core_facts corr_B 的 projection 仍在（不同 field 不 suppression）
    core_act = [it for it in base8["memory"]["core_facts"] if it.get("status") == "active"]
    C.ok("8: different field not suppressed",
         any(it.get("correction_id") == "corr_B" for it in core_act), str([a.get("correction_id") for a in core_act]))

    # ---- 9: multi-candidate unresolved not force-merged ----
    #   loader 只 omit F5-e 明确判 superseded 的；ambiguous lane（无 supersede verdict）不 omit
    core9 = [{"id": "mi_A", "content": "她话少", "status": "superseded", "confidence": 0.8,
              "importance": 1, "source_type": "user_input"},
             {"id": "mi_B", "content": "旧B", "status": "superseded", "confidence": 0.8,
              "importance": 1, "source_type": "user_input"}]
    pm9 = longterm_pm([corr("corr_B1", "mi_A", corrected_value="话痨一"),
                       corr("corr_B2", "mi_B", corrected_value="话痨二")], core_mem=core9)
    C9 = overlay("memory", "memory.core_facts", "某新说法", "mi_C9", target_id=None, at="t9")
    base9 = load_runtime_persona(pm9, [C9])
    # C9 target_id=None → F5-e 不 supersede corr_B1/B2 → loader 不 omit（不强行合并）
    b1_act = any(it.get("correction_id") == "corr_B1" and it.get("status") == "active"
                 for it in base9["memory"]["core_facts"])
    b2_act = any(it.get("correction_id") == "corr_B2" and it.get("status") == "active"
                 for it in base9["memory"]["core_facts"])
    C.ok("9: ambiguous not force-merged/suppressed", b1_act and b2_act, f"B1={b1_act} B2={b2_act}")

    # ---- 10: rejected/superseded correction not reactivated ----
    pm10 = longterm_pm([corr("corr_R", "mi_A", status="rejected")])
    base10 = load_runtime_persona(pm10, [])
    C.ok("10: rejected correction not projected/active",
         not any(it.get("correction_id") == "corr_R" for it in base10["memory"]["core_facts"]))
    pm10b = longterm_pm([corr("corr_S", "mi_A", status="superseded")])
    base10b = load_runtime_persona(pm10b, [])
    C.ok("10: superseded correction not projected/active",
         not any(it.get("correction_id") == "corr_S" for it in base10b["memory"]["core_facts"]))

    # ---- 11: persona correction not in memory lane ----
    #   base 允许原有 memory 项存在；断言 persona correction 不新增 projection
    pm11 = longterm_pm([corr("corr_P", "pc_1", target_kind="persona_claim", field="persona.speech_style",
                             corrected_value="我话少")])
    base11 = load_runtime_persona(pm11, [])
    proj11 = [it for b in base11["memory"] for it in base11["memory"][b] if it.get("correction_id")]
    C.ok("11: persona correction not projected to memory", len(proj11) == 0, str(proj11))

    # ---- 12: new session sees long-term active correction ----
    pm12 = longterm_pm([corr("corr_B", "mi_A")])
    base12 = load_runtime_persona(pm12, [])  # 无 session overlay
    C.ok("12: new session (no overlay) sees B projection",
         any(it.get("correction_id") == "corr_B" for it in active_items(base12)))

    # ---- 13: PM bytes unchanged ----
    pm13 = longterm_pm([corr("corr_B", "mi_A")])
    b = json.dumps(pm13, ensure_ascii=False, sort_keys=True)
    load_runtime_persona(pm13, [overlay("memory", "memory.core_facts", "x", "mi_x", target_id="mi_A")])
    C.ok("13: PM bytes unchanged", json.dumps(pm13, ensure_ascii=False, sort_keys=True) == b)

    print(f"\n通过 {C.ok_n} / 失败 {C.fail_n}")
    for f in C.fails:
        print("  -", f)
    sys.exit(0 if C.fail_n == 0 else 1)


if __name__ == "__main__":
    main()
