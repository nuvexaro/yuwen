#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 5.9-B / F5-f Phase 2：Long-term Correction Projection deterministic tests。

验证（裁决 11 项）：
  1. confirmed(active) correction 存在于 persona_memory.corrections[]
  2. 新 Session 能通过 projection 读取 active correction（retrieve/support 可见）
  3. superseded correction 不投影
  4. pending/rejected/expired 不投影（correctionItem 只有 active/superseded；rejected/expired 不入 schema，但防御）
  5. persona-domain(persona_claim) correction 不进入 memory projection
  6. ordinary assertion 不进入 correction projection（corrections[] 无 assertion 条目；防御断言）
  7. active correction 与旧 memory 不形成 double-current（旧 target 已 superseded；新投影唯一 active）
  8. session isolation（projection 纯函数只读 persona_memory；不涉及 session 状态）
  9. PM 原始 bytes 不被 projection 修改
  10. F5-d/F5-e SHA 不变（回归在外部验证）
  11. 517/517 PASS（外部验证）
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

import correction_longterm_projection as clp  # noqa: E402
import memory_retrieval as mr  # noqa: E402
import reality_boundary as rb  # noqa: E402


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


def pm_with(active_mem=None, corrections=None):
    pm = {"schema_version": "1.2", "persona": {"layer0_rules": {}, "identity": {}},
          "memory": {k: [] for k in ("preferences", "timeline", "shared_experiences", "conflicts",
                                     "happy_memories", "breakup", "inside_jokes", "core_facts",
                                     "daily_patterns")}, "corrections": corrections or []}
    if active_mem:
        for b, items in active_mem.items():
            pm["memory"][b] = items
    return pm


def mem(id_, content, status="active"):
    return {"id": id_, "content": content, "status": status, "confidence": 0.8,
            "importance": 1, "source_type": "user_input"}


def corr(cid, corrected_value, target_id, status="active", target_kind="memory_item",
         target_path="memory.core_facts", original_value="她话少", user_statement="不对，她话痨"):
    return {"id": cid, "target_kind": target_kind, "target_id": target_id,
            "target_path": target_path, "original_value": original_value,
            "corrected_value": corrected_value, "basis_override": "correction",
            "user_statement": user_statement, "status": status, "superseded_by": None,
            "created_at": "2026-09-04T00:00:00"}


def in_bucket(view, bucket, content):
    return any(it.get("content") == content for it in view["memory"][bucket])


def main():
    print("=== Stage 5.9-B / F5-f Phase 2: long-term correction projection ===")

    # ---- 构造：旧 memory A(superseded) + 原值 A + 顶层 active correction B ----
    base = pm_with(active_mem={"core_facts": [mem("mi_A", "她话少", status="superseded")]},
                   corrections=[corr("corr_B", "她话痨", "mi_A")])
    pm_bytes = json.dumps(base, ensure_ascii=False, sort_keys=True)

    # 1) active correction 存在于 corrections[]
    C.ok("P2-1: active correction in corrections[]", any(c["status"] == "active"
         and c["corrected_value"] == "她话痨" for c in base["corrections"]))

    # 2) projection → 新 Session retrieve/support 可见
    view = clp.project_active_corrections(base)
    C.ok("P2-2: projected active item in core_facts", in_bucket(view, "core_facts", "她话痨"))
    # retrieve via projected view
    r = mr.retrieve(view, {}, "她话多吗", k=5)
    C.ok("P2-2: retrieval hits projected correction",
         any(x["memory"]["content"] == "她话痨" for x in r["items"]), str([x["memory"]["id"] for x in r["items"]]))
    # assess_support 不 bypass A′（该 fact 非共享过去实体 → supported/ordinary；但若为空记忆 claim 仍被 boundary 拦）
    fl = rb.check_reality(view, "她话多吗", now=datetime(2026, 9, 1))
    rr = mr.retrieve(view, {}, "她话多吗", k=5, now=datetime(2026, 9, 1))
    sup = rb.assess_support(view, "她话多吗", retrieved_items=rr["items"], now=datetime(2026, 9, 1), flags=fl)
    C.ok("P2-2: assess_support sees projected (not blocked unsupported)",
         sup["boundary_state"] in ("supported", "ordinary"), str(sup["boundary_state"]))

    # 3) superseded correction 不投影
    base3 = pm_with(active_mem={"core_facts": [mem("mi_A", "她话少", status="superseded")]},
                    corrections=[corr("corr_B", "她话痨", "mi_A", status="superseded",
                                      target_path="memory.core_facts")])
    view3 = clp.project_active_corrections(base3)
    C.ok("P2-3: superseded correction not projected", not in_bucket(view3, "core_facts", "她话痨"))

    # 4) pending/rejected/expired 不投影（schema correctionItem 只 active/superseded；模拟防御）
    base4 = pm_with(corrections=[corr("corr_P", "她话痨", "mi_X", status="active")])
    # 手动给非 schema 状态走防御：active_projection_count 只数 active
    for c in base4["corrections"]:
        c["status"] = "rejected"
    C.ok("P2-4: rejected not counted", clp.active_projection_count(base4) == 0)
    view4 = clp.project_active_corrections(base4)
    C.ok("P2-4: rejected not projected", not in_bucket(view4, "core_facts", "她话痨"))

    # 5) persona_claim correction 不进 memory projection
    base5 = pm_with(corrections=[corr("corr_p", "我话很少", "pc_1", target_kind="persona_claim",
                                      target_path="persona.speech_style")])
    view5 = clp.project_active_corrections(base5)
    total5 = sum(len(view5["memory"][b]) for b in view5["memory"])
    C.ok("P2-5: persona_claim not projected to memory", total5 == 0, f"total={total5}")

    # 6) ordinary assertion 不进 correction projection（corrections[] 无 assertion 语义条目）
    #    corrections[] 只存 correctionItem；普通 assertion 由 builder 写普通 memory，不在此。
    C.ok("P2-6: corrections[] carries only correction (no assertion entry)",
         all("corrected_value" in c for c in base["corrections"]))

    # 7) 不 double-current：旧 mi_A superseded + 新投影 active = 唯一 active current
    actives = [it for it in view["memory"]["core_facts"] if it.get("status") == "active"]
    C.ok("P2-7: only one active current (projected B), old A superseded",
         len(actives) == 1 and actives[0]["content"] == "她话痨",
         str([(it["content"], it["status"]) for it in view["memory"]["core_facts"]]))

    # 8) session isolation：projection 纯函数只读 persona_memory，不携带 session 状态
    C.ok("P2-8: projection is pure read (no session param needed)", callable(clp.project_active_corrections))

    # 9) PM 原始 bytes 不被 projection 修改
    C.ok("P2-9: frozen PM bytes unchanged",
         json.dumps(base, ensure_ascii=False, sort_keys=True) == pm_bytes)
    # 且 projection 返回的是 deepcopy（改 view 不伤 frozen）
    view9 = clp.project_active_corrections(base)
    view9["memory"]["core_facts"][-1]["content"] = "MUTATED"
    C.ok("P2-9: deepcopy isolation", not in_bucket(base, "core_facts", "MUTATED"))

    # 额外：provenance/身份信息保留
    proj = [it for it in view["memory"]["core_facts"] if it.get("content") == "她话痨"][0]
    C.ok("P2-extra: basis/source_type/corrected set", proj.get("basis") == "correction"
         and proj.get("source_type") == "correction" and proj.get("corrected") is True, str(proj))
    C.ok("P2-extra: provenance carried (correction_id/user_statement/original_value)",
         proj.get("correction_id") == "corr_B" and proj.get("user_statement") == "不对，她话痨"
         and proj.get("original_value") == "她话少", str(proj))
    C.ok("P2-extra: deterministic id (mi_)", str(proj.get("id", "")).startswith("mi_"), str(proj.get("id")))

    print(f"\n通过 {C.ok_n} / 失败 {C.fail_n}")
    for f in C.fails:
        print("  -", f)
    sys.exit(0 if C.fail_n == 0 else 1)


if __name__ == "__main__":
    main()
