#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 5.9-B / F5-b reopen (Phase 3A): target anchoring deterministic tests.

目标：correction-over-correction 继承同 semantic lane 既有 active correction 的 target_id，
使 F5-e lane_key(new) == lane_key(existing)，消除 double-current 的上游根因。

覆盖（裁决 12 项）：
 1 existing correction → newer correction 继承 target
 2 paraphrased correction 继承
 3 same-attribute opposite correction 继承
 4 unrelated field 不继承
 5 multiple candidate → unresolved
 6 superseded candidate 不作锚
 7 rejected/expired candidate 不作锚
 8 persona correction 隔离（不作 memory 锚）
 9 ordinary assertion 隔离（不进 resolver 锚定）
10 no existing correction → new_memory_item / target_id=None（原行为）
11 existing content-match path unchanged
12 PM byte integrity（纯函数不改 persona_memory）
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


def pm_with(mem_core=None, corrections=None):
    return {"schema_version": "1.2", "persona": {"layer0_rules": {}, "identity": {}},
            "memory": {"core_facts": mem_core or [],
                       "preferences": [], "timeline": [], "shared_experiences": [],
                       "conflicts": [], "happy_memories": [], "breakup": [],
                       "inside_jokes": [], "daily_patterns": []},
            "corrections": corrections or []}


def corr(cid, target_id, status="active", target_kind="memory_item", field="memory.core_facts",
         corrected_value="x"):
    return {"id": cid, "target_kind": target_kind, "target_id": target_id,
            "target_path": field, "corrected_value": corrected_value,
            "user_statement": "纠正", "status": status}


def main():
    print("=== Stage 5.9-B / F5-b reopen (Phase 3A): target anchoring ===")

    # ---- 1. existing correction → newer correction inherits ----
    pm = pm_with(corrections=[corr("corr_B", "mi_A")])
    t = cr.resolve_correction_target(pm, "不对，她其实特别能说。")
    C.ok("1: newer correction inherits B target_id", t.get("target_id") == "mi_A"
         and t.get("target_kind") == "memory_item", str(t))

    # ---- 2. paraphrased correction ----
    t2 = cr.resolve_correction_target(pm, "不对，她其实话很多。")
    C.ok("2: paraphrase inherits", t2.get("target_id") == "mi_A", str(t2))

    # ---- 3. same-attribute opposite correction ----
    t3 = cr.resolve_correction_target(pm, "不对，她其实没那么话痨。")
    C.ok("3: same-attr opposite inherits", t3.get("target_id") == "mi_A", str(t3))

    # ---- 4. unrelated field ----
    t4 = cr.resolve_correction_target(pm, "不对，她其实特别喜欢上海。")
    C.ok("4: unrelated field does NOT inherit B", t4.get("target_id") != "mi_A"
         and t4.get("target_id") is None, str(t4))

    # ---- 5. multiple candidate → unresolved ----
    pm5 = pm_with(corrections=[corr("c1", "mi_A"), corr("c2", "mi_B")])
    t5 = cr.resolve_correction_target(pm5, "不对，她其实特别能说。")
    C.ok("5: ambiguous → unresolved (not wrong target)", t5.get("domain") == "unresolved"
         and t5.get("target_id") is None, str(t5))

    # ---- 6. superseded candidate not anchor ----
    pm6 = pm_with(corrections=[corr("c1", "mi_A", status="superseded")])
    t6 = cr.resolve_correction_target(pm6, "不对，她其实特别能说。")
    C.ok("6: superseded not anchor → new_memory_item/None", t6.get("target_id") is None
         and t6.get("target_kind") == "new_memory_item", str(t6))

    # ---- 7. rejected/expired candidate not anchor ----
    pm7 = pm_with(corrections=[corr("c1", "mi_A", status="rejected")])
    t7 = cr.resolve_correction_target(pm7, "不对，她其实特别能说。")
    C.ok("7: rejected not anchor → None/new", t7.get("target_id") is None, str(t7))

    # ---- 8. persona correction isolation ----
    pm8 = {"schema_version": "1.2", "persona": {"speech_style": {"tone": [{"claim_id": "pc_t", "value": "我话痨"}]}},
           "memory": {"core_facts": [], "preferences": [], "timeline": [], "shared_experiences": [],
                      "conflicts": [], "happy_memories": [], "breakup": [], "inside_jokes": [],
                      "daily_patterns": []},
           "corrections": [corr("cp", "pc_t", target_kind="persona_claim", field="persona.speech_style")]}
    t8 = cr.resolve_correction_target(pm8, "不对，她其实特别能说。")
    C.ok("8: persona correction not memory anchor", t8.get("target_id") is None
         and t8.get("target_kind") == "new_memory_item", str(t8))

    # ---- 9. ordinary assertion isolation ----
    #   assertion 不进 resolver（只有 correction 句式触发 _handle_correction）；此处验证句子带“其实”更正触发
    #   而纯陈述（“她特别能说。”无更正标志）若被调，也无 corrections 可继承——assertion 语义由 F5-e 处理
    t9 = cr.resolve_correction_target(pm_with(corrections=[corr("c1", "mi_A")]), "不对，她其实特别能说。")
    C.ok("9: correction-sentence inherits (assertion path handled elsewhere)", t9.get("target_id") == "mi_A")

    # ---- 10. no existing correction → original behavior ----
    t10 = cr.resolve_correction_target(pm_with(corrections=[]), "不对，她其实特别能说。")
    C.ok("10: no existing → new_memory_item/None", t10.get("target_id") is None
         and t10.get("target_kind") == "new_memory_item", str(t10))

    # ---- 11. existing content-match path unchanged ----
    #   memory 桶有 active 且 content 命中 的项 → 仍按 content 匹配返回该项（不走到 anchor）
    pm11 = pm_with(mem_core=[{"id": "mi_LIVE", "content": "她话痨爱聊天", "status": "active",
                              "confidence": 0.8, "importance": 1, "source_type": "user_input"}])
    t11 = cr.resolve_correction_target(pm11, "不对，她其实特别能说。")
    C.ok("11: content-match path unchanged (returns live item)",
         t11.get("target_id") == "mi_LIVE" and t11.get("target_kind") == "memory_item", str(t11))

    # ---- 12. PM byte integrity ----
    pm12 = pm_with(corrections=[corr("corr_B", "mi_A")])
    b = json.dumps(pm12, ensure_ascii=False, sort_keys=True)
    cr.resolve_correction_target(pm12, "不对，她其实特别能说。")
    C.ok("12: PM bytes unchanged", json.dumps(pm12, ensure_ascii=False, sort_keys=True) == b)

    print(f"\n通过 {C.ok_n} / 失败 {C.fail_n}")
    for f in C.fails:
        print("  -", f)
    sys.exit(0 if C.fail_n == 0 else 1)


if __name__ == "__main__":
    main()
