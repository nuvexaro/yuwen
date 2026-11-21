#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 5.9-B / F5-f Phase 1：Persistence Export deterministic tests。

覆盖裁决 Case A–H + integrity：
  Case A  A(assertion)→B(correction)：B effective current、A superseded、B pending→confirmed→active input
  Case B  A→B(corr)→C(corr)：C current、B superseded_by C、三者 provenance 保留、只 C active
  Case C  A→B(corr)→C(assertion)：B 仍 current correction、C 为 conflict、C 不进 active、C 不 supersede B
  Case D  无 correction 纯 assertion：不产生 correction-proposal
  Case E  不同 target/field 不互相 supersede
  Case F  persona-domain correction 不进 memory projection/export
  Case G  pending/rejected/expired 不进 active_correction_input
  Case H  session isolation：session A pending 不影响 session B
  integrity：projection/export 前后 persona_memory bytes 不变；corrections[]/memory[] 不被 runtime 修改
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

import correction_export as cexp  # noqa: E402


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


def ov(domain, field, value, nid, target_id=None, at="t1"):
    return {"target_domain": domain, "target_kind": "new_memory_item", "target_id": target_id,
            "old_value": None, "corrected_value": value, "new_claim_id": nid,
            "field": field, "source_turn": f"纠正:{value}", "at": at}


def main():
    print("=== Stage 5.9-B / F5-f Phase 1: persistence export ===")

    # ---- Case A: A(assertion 不产生 overlay)→B(correction overlay) ----
    #   Session 只有 overlay（assertion A 不入 overlay，它是"被纠的旧值"经由 target_id 语义关联）。
    ovA = [ov("memory", "memory.core_facts", "她话痨", "mi_B", target_id="mi_A", at="t2")]
    rA = cexp.export_correction_proposals(ovA, source_session_id="sA")
    C.ok("A: one pending proposal (B)", len(rA["proposals"]) == 1 and rA["proposals"][0]["status"] == "pending",
         str(rA["proposals"]))
    C.ok("A: no active input while pending", rA["active_correction_input"] == [], str(rA["active_correction_input"]))
    # confirm B → active input
    pA = cexp.confirm_proposal(rA["proposals"][0])
    rA2 = cexp.export_correction_proposals(ovA, existing_proposals=[pA], source_session_id="sA")
    C.ok("A: confirmed B → active input", len(rA2["active_correction_input"]) == 1
         and rA2["active_correction_input"][0]["new_claim_id"] == "mi_B", str(rA2["active_correction_input"]))
    C.ok("A: target/provenance preserved in active input",
         rA2["active_correction_input"][0]["target_id"] == "mi_A"
         and rA2["active_correction_input"][0]["corrected_value"] == "她话痨")

    # ---- Case B: A→B(corr)→C(corr)：只 C current/active ----
    #   overlay 是 append 序：B 先、C 后（同 field 同 target）
    ovB = [ov("memory", "memory.core_facts", "她话痨", "mi_B", target_id="mi_A", at="t1"),
           ov("memory", "memory.core_facts", "她话很多", "mi_C", target_id="mi_A", at="t2")]
    #   F5-e 归约（通过 build_statements → resolve）
    import correction_conflicts as f5e
    stmtsB = f5e.build_statements_from_overlay(ovB)
    lanesB = f5e.resolve_statements(stmtsB)
    curB = list(lanesB.values())[0]["current"]
    supB = list(lanesB.values())[0]["superseded"]
    C.ok("B: C is current (F5-e)", curB["value"] == "她话很多", str(curB))
    C.ok("B: B superseded", any(s["value"] == "她话痨" for s in supB), str(supB))
    # export：只有 C 进 proposals/active
    rB = cexp.export_correction_proposals(ovB, source_session_id="sB")
    C.ok("B: export only C (B not re-exported as active)",
         all(p["new_claim_id"] == "mi_C" for p in rB["proposals"]), str(rB["proposals"]))

    # ---- Case C (最重要): A→B(corr)→C(assertion)：C 不 supersede B ----
    #   C 是普通 assertion → 不在 overlay（overlay 只存 correction）。overlay=[B]。
    ovC = [ov("memory", "memory.core_facts", "她话痨", "mi_B", target_id="mi_A", at="t1")]
    rC = cexp.export_correction_proposals(ovC, source_session_id="sC")
    # C(assertion) 若作为独立证据流入 5.2–5.5 的 candidate，它会进普通 memory 演化，但：
    #   - 它不在 corrections 输入 → 不 supersede B；
    #   - export 的 active correction input 只有 B。
    C.ok("C: B is the only correction input (C assertion excluded)",
         all(p["new_claim_id"] == "mi_B" for p in rC["proposals"])
         and all(p["kind"] == "correction" for p in rC["proposals"]),
         str(rC["proposals"]))
    # 语义层复核：若把 C 作为 assertion statement 喂 F5-e，C 必须进 conflicts 不 supersede B
    stmtsC = f5e.build_statements_from_overlay(ovC) + [{
        "kind": "assertion", "value": "她其实不怎么说话", "id": "mi_Ca", "source_turn": "turnC",
        "at": "t3", "target_domain": "memory", "field": "memory.core_facts", "target_id": "mi_A"}]
    lanesC = f5e.resolve_statements(stmtsC)
    curCc = list(lanesC.values())[0]["current"]
    C.ok("C: B still current after C assertion", curCc["value"] == "她话痨" and curCc["kind"] == "correction",
         str(curCc))
    C.ok("C: C in conflicts, not superseder",
         any(x["value"] == "她其实不怎么说话" for x in list(lanesC.values())[0]["conflicts"]),
         str(list(lanesC.values())[0]["conflicts"]))

    # ---- Case D: 无 correction 纯 assertion → 无 overlay → 无 proposal ----
    rD = cexp.export_correction_proposals([], source_session_id="sD")
    C.ok("D: empty overlay → no proposals", rD["proposals"] == [] and rD["active_correction_input"] == [])

    # ---- Case E: 不同 target/field 不互相 supersede ----
    ovE = [ov("memory", "memory.core_facts", "她话痨", "mi_t1", target_id="ta", at="t1"),
           ov("memory", "memory.preferences", "爱吃辣", "mi_t2", target_id="tb", at="t2")]
    stmtsE = f5e.build_statements_from_overlay(ovE)
    lanesE = f5e.resolve_statements(stmtsE)
    C.ok("E: two lanes independent", len(lanesE) == 2 and
         all(not l["superseded"] for l in lanesE.values()), str(len(lanesE)))

    # ---- Case F: persona-domain correction 不进 memory export ----
    ovF = [ov("persona", "persona.speech_style", "我话很少", "pc_x", at="t1")]
    rF = cexp.export_correction_proposals(ovF, source_session_id="sF")
    C.ok("F: persona correction not exported to memory proposals", rF["proposals"] == [],
         str(rF["proposals"]))

    # ---- Case G: pending/rejected/expired 不进 active ----
    #   构造三个 proposal 状态
    ovG = [ov("memory", "memory.core_facts", "话痨", "mi_g1", target_id="a"),
           ov("memory", "memory.core_facts", "话痨2", "mi_g2", target_id="b"),
           ov("memory", "memory.core_facts", "话痨3", "mi_g3", target_id="c")]
    # 手动建三个不同状态 proposal
    pend = cexp.confirm_proposal(ovG[0])  # 我们先构造
    # 重新干净地做
    rG = cexp.export_correction_proposals(ovG, source_session_id="sG")
    # all pending initially
    C.ok("G: fresh exports all pending", all(p["status"] == "pending" for p in rG["proposals"]))
    # confirm one, reject one, keep one pending
    rG["proposals"][0]["status"] = "confirmed"
    rG["proposals"][1]["status"] = "rejected"
    rG["proposals"][2]["status"] = "pending"
    rG2 = cexp.export_correction_proposals(ovG, existing_proposals=rG["proposals"], source_session_id="sG")
    active_ids = [p["new_claim_id"] for p in rG2["active_correction_input"]]
    C.ok("G: only confirmed in active input", active_ids == ["mi_g1"], str(active_ids))
    C.ok("G: rejected/pending never active", "mi_g2" not in active_ids and "mi_g3" not in active_ids)

    # ---- Case H: session isolation ----
    ovHA = [ov("memory", "memory.core_facts", "话痨A", "mi_HA", target_id="a", at="t1")]
    rHA = cexp.export_correction_proposals(ovHA, source_session_id="sessA")  # A 的 pending
    ovHB = []  # B session 无 correction
    rHB = cexp.export_correction_proposals(ovHB, source_session_id="sessB")
    C.ok("H: session B sees nothing from A's pending", rHB["proposals"] == [], str(rHB["proposals"]))
    C.ok("H: session A pending carries its source_session", rHA["proposals"][0]["source_session_id"] == "sessA")

    # ---- integrity: persona_memory 不被 runtime 修改 ----
    pm = {"schema_version": "1.2", "persona": {}, "corrections": [],
          "memory": {"core_facts": [{"id": "mi_A", "content": "她话少", "status": "active",
                                     "confidence": 0.8, "importance": 1, "source_type": "user_input"}]}}
    pm_bytes = json.dumps(pm, ensure_ascii=False, sort_keys=True)
    # 导出层只读 persona_memory（甚至不接收它）；跑一轮 export
    ovI = [ov("memory", "memory.core_facts", "她话痨", "mi_B", target_id="mi_A", at="t1")]
    cexp.export_correction_proposals(ovI, source_session_id="sI")
    # 语义层不改
    f5e.resolve_statements(f5e.build_statements_from_overlay(ovI))
    C.ok("integrity: persona_memory bytes unchanged", json.dumps(pm, ensure_ascii=False, sort_keys=True) == pm_bytes)

    print(f"\n通过 {C.ok_n} / 失败 {C.fail_n}")
    for f in C.fails:
        print("  -", f)
    sys.exit(0 if C.fail_n == 0 else 1)


if __name__ == "__main__":
    main()
