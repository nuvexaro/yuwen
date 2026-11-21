#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 5.9-B / F5 Phase-1：Recorded → Correct Target → Session Adoption。

T1 第三人称“她”+性格纠正 → target memory 域，绝不 speech_style.catchphrases[0]
T2 第一人称“我”+话少纠正 → target persona/speech_style
T3 明确 correction → recorded+targeted+overlay_created
T4 普通非 correction → 不创建 overlay
T5 correction 后下一轮普通对话 → system context 仍含 overlay
T6 correction 后直接问 → context 含 corrected value
T7 persona_memory bytes 前后不变
T8 target unresolved → 不错误覆盖任意已有 claim
"""

from __future__ import annotations

import copy
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
import persona_constraints as pc  # noqa: E402
import context_assembly as ca  # noqa: E402
import correction_runtime as cr  # noqa: E402
import persona_runtime as pr  # noqa: E402
from persona_runtime import PersonaRuntime  # noqa: E402
from llm_gateway import LLMGateway  # noqa: E402
import session_store as ss  # noqa: E402


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


def claim(field, value, basis="direct_quote"):
    cid = None
    try:
        import persona_memory_builder as pmb
        cid = pmb.claim_id(field, value)
    except Exception:
        cid = "pc_" + value[:8]
    return {"claim_id": cid, "value": value, "evidence_ids": ["c_1"],
            "confidence": 0.9, "basis": basis}


def sample_pm():
    return {"schema_version": "1.2", "revision": 1, "persona": {
        "layer0_rules": {"do_not_say": [], "specific_edges": [], "reality_boundary": None},
        "identity": {"name_or_alias": claim("identity.name_or_alias", "小明", "user_report_only"),
                     "relationship": {}},
        "speech_style": {"catchphrases": [claim("speech_style.catchphrases", "哈哈哈哈")],
                         "examples": [], "punctuation": None,
                         "tone": [claim("speech_style.tone", "简短冷淡")]},
        "emotional_pattern": {}, "relationship_behavior": {}},
        "memory": {k: [] for k in ("preferences", "timeline", "shared_experiences", "conflicts",
                                   "happy_memories", "breakup", "inside_jokes", "core_facts",
                                   "daily_patterns")},
        "corrections": []}


def bytes_of(pm):
    return json.dumps(pm, ensure_ascii=False, sort_keys=True)


def run_seq(pm, turns, responder=None):
    """在单 session 跑多轮，返回 (runtime, responses, session)。"""
    g = LLMGateway(adapter=responder or (lambda p, **k: "嗯 知道了。"), model="mock")
    rt = PersonaRuntime(persona_memory=pm, gateway=g)
    sid = None
    out = []
    for t in turns:
        r = rt.respond(t, session_id=sid)
        if sid is None:
            sid = r["session_update"]["session_id"]
        out.append(r)
    return rt, out, rt.store.get(sid)


def main():
    print("=== Stage 5.9-B / F5 Phase-1: recorded→targeted→adoption ===")

    # ---------- T1: 第三人称“她”+话痨 → memory 域 ----------
    pm = sample_pm()
    pm_before = bytes_of(pm)
    catch_cid = pm["persona"]["speech_style"]["catchphrases"][0]["claim_id"]
    rt, out, s = run_seq(pm, ["不对，她其实特别话痨。"])
    cc = out[0]["correction_result"]
    C.ok("T1: detected", cc is not None and cc.get("detected") is True)
    C.ok("T1: target domain = memory", cc is not None and cc.get("target_domain") == "memory",
         json.dumps(cc, ensure_ascii=False))
    C.ok("T1: NOT catchphrase[0]", cc is not None and cc.get("old_claim_id") != catch_cid, cc.get("old_claim_id"))
    C.ok("T1: overlay created (memory new item)", s is not None and len(s.persona_overlay) >= 1
         and s.persona_overlay[0]["target_domain"] == "memory", str(s.persona_overlay if s else None))
    C.ok("T1: T7 persona_memory bytes unchanged", bytes_of(pm) == pm_before)

    # ---------- T2: 第一人称“我”话少 → persona/speech_style ----------
    pm2 = sample_pm()
    rt2, out2, s2 = run_seq(pm2, ["不对，我其实话很少。"])
    cc2 = out2[0]["correction_result"]
    C.ok("T2: target domain = persona", cc2 is not None and cc2.get("target_domain") == "persona",
         json.dumps(cc2, ensure_ascii=False))
    C.ok("T2: overlay target persona", s2 is not None and len(s2.persona_overlay) >= 1
         and s2.persona_overlay[0]["target_domain"] == "persona")

    # ---------- T3: recorded + targeted + overlay_created ----------
    C.ok("T3: recorded=true", cc is not None and cc.get("applied_overlay") is True)
    C.ok("T3: new_claim_id deterministic", cc is not None and cc.get("new_claim_id"))
    rt3, out3, s3 = run_seq(sample_pm(), ["不对，她其实特别话痨。"])
    cc3 = out3[0]["correction_result"]
    C.ok("T3: rerun stable id", cc3 and cc.get("new_claim_id") == cc3.get("new_claim_id"))

    # ---------- T4: 非 correction 不建 overlay ----------
    pm4 = sample_pm()
    rt4, out4, s4 = run_seq(pm4, ["在干嘛", "哈哈 笑死我了"])
    C.ok("T4: no overlay for non-correction", s4 is not None and len(s4.persona_overlay) == 0,
         str(s4.persona_overlay if s4 else None))

    # ---------- T5: correction 后下一轮普通对话仍含 overlay ----------
    pm5 = sample_pm()
    rt5, out5, s5 = run_seq(pm5, ["不对，她其实特别话痨。", "今天天气不错"])
    ctx5 = ca.assemble(pm5, "小明", "今天天气不错",
                       reality_flags=rb.check_reality(pm5, "今天天气不错"),
                       session_recent=s5.recent(8), session_overlay=s5.persona_overlay)
    C.ok("T5: overlay in next-turn system context", "话痨" in ctx5["system_text"]
         and "已确认信息" in ctx5["system_text"], ctx5["system_text"][-200:])

    # ---------- T6: correction 后直接问 → context 含 corrected value ----------
    pm6 = sample_pm()
    rt6, out6, s6 = run_seq(pm6, ["不对，她其实特别话痨。", "她话多话少？"])
    ctx6 = ca.assemble(pm6, "小明", "她话多话少？",
                       reality_flags=rb.check_reality(pm6, "她话多话少？"),
                       session_recent=s6.recent(8), session_overlay=s6.persona_overlay)
    C.ok("T6: direct-ask context has corrected value", "话痨" in ctx6["system_text"], ctx6["system_text"][-200:])

    # ---------- T7: persona_memory bytes（已并入 T1，单列一次）----------
    pm7 = sample_pm()
    b0 = bytes_of(pm7)
    run_seq(pm7, ["不对，她其实特别话痨。"])
    C.ok("T7: persona_memory unchanged (dedicated)", bytes_of(pm7) == b0)

    # ---------- T8: target unresolved 不覆盖任意已有 claim ----------
    pm8 = sample_pm()
    # 无主体/无属性、难定位的纠正 → unresolved，绝不写 overlay/不覆盖已有 claim
    rt8, out8, s8 = run_seq(pm8, ["不对，不是那样。"])
    cc8 = out8[0]["correction_result"]
    C.ok("T8: unresolved not forced to a claim",
         cc8 is None or cc8.get("target_domain") in ("unresolved", None)
         or cc8.get("applied_overlay") is False, json.dumps(cc8, ensure_ascii=False))
    C.ok("T8: no overlay written on unresolved", s8 is None or len(s8.persona_overlay) == 0,
         str(s8.persona_overlay if s8 else None))

    print(f"\n通过 {C.ok_n} / 失败 {C.fail_n}")
    for f in C.fails:
        print("  -", f)
    sys.exit(0 if C.fail_n == 0 else 1)


if __name__ == "__main__":
    main()
