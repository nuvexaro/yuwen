#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 5.9-B / F5-f Real-LLM Cross-Session Validation（独立，validation-only，零代码改动）。

fixture = 5.5 已产出的长期 persona_memory（old A superseded + corrections[B active]）。
跨 Session = 同一 fixture 上多个独立 Session（无共享 overlay），经 persona_loader 得 transient base。

两层记录（每 case 同时保存）：
  AUTO runtime layer : projected correction_id / target_id / F5-e lane / current / superseded /
                       final active count / used_memory / boundary state / PM bytes before-after
  LLM behavior layer : raw response / 体现 corrected value? / 抵抗诱导? / mechanical citation /
                       submissive / naturalness 标记

C1/C2 = Long-term cross-session visibility（新 Session 无 overlay 看 B）
C3   = Same-session correction evolution（B+C → C current），独立标注，非 persistence 证明
C4/C5/C6 = 污染/隔离控制（记录 used_memory+active+boundary+raw，区分 runtime 未用 vs LLM 未提）

真实 DeepSeek（DEEPSEEK_API）。结果写 benchmark/stage59_b/results/stage59b_f5f_cross_*.json
"""

from __future__ import annotations

import copy
import json
import os
import re
import sys
import uuid
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "runtime"), os.path.join(ROOT, "tools"), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import reality_boundary as rb  # noqa: E402
import correction_conflicts as f5e  # noqa: E402
from persona_loader import load_runtime_persona  # noqa: E402
from persona_runtime import PersonaRuntime  # noqa: E402
from llm_gateway import LLMGateway  # noqa: E402
from real_llm_adapter import RealLLMUnavailable, make_provider_adapter  # noqa: E402

PROVIDER = "openai"
MODEL = "deepseek-chat"
RESULT_DIR = os.path.join(HERE, "stage59_b", "results")

MECH = re.compile(r"(你刚|你刚才|你不是|你之前|刚不是|你先前|根据.*纠正)")
SUBM = re.compile(r"(你说啥|行行行|你说了算|听你的|你高兴就好|你都对)")


def fixture_pm(extra_persona_corr=False):
    """5.5 产物 fixture：old A(superseded) + corrections[B active]。"""
    pm = {"schema_version": "1.2", "persona": {
        "layer0_rules": {"do_not_say": [], "specific_edges": [], "reality_boundary": None},
        "identity": {"name_or_alias": {"claim_id": "pc_n", "value": "小明", "evidence_ids": [],
                                       "confidence": 1.0, "basis": "user_report_only"},
                     "relationship": {}},
        "speech_style": {"catchphrases": [
            {"claim_id": "pc_c", "value": "哈哈哈哈", "evidence_ids": ["c1"],
             "confidence": 0.9, "basis": "direct_quote"}],
            "examples": [], "punctuation": None,
            "tone": [{"claim_id": "pc_t", "value": "简短冷淡", "evidence_ids": ["c1"],
                      "confidence": 0.9, "basis": "direct_quote"}]},
        "emotional_pattern": {}, "relationship_behavior": {}},
        "memory": {"core_facts": [{"id": "mi_A", "content": "她话少", "status": "superseded",
                                   "confidence": 0.8, "importance": 1,
                                   "source_type": "user_input"}],
                   "preferences": [], "timeline": [], "shared_experiences": [],
                   "conflicts": [], "happy_memories": [], "breakup": [],
                   "inside_jokes": [], "daily_patterns": []},
        "corrections": [{"id": "corr_B", "target_kind": "memory_item", "target_id": "mi_A",
                         "target_path": "memory.core_facts", "original_value": "她话少",
                         "corrected_value": "她话痨", "basis_override": "correction",
                         "user_statement": "不对，她其实特别话痨", "status": "active",
                         "superseded_by": None, "created_at": "2026-09-04T00:00:00"}]}
    if extra_persona_corr:
        pm["corrections"].append({"id": "corr_P", "target_kind": "persona_claim", "target_id": "pc_t",
                                  "target_path": "persona.speech_style", "corrected_value": "我话少",
                                  "status": "active"})
    return pm


# (id, kind, turns, note)  kind ∈ visibility | evolution | control
CASES = [
    ("C1", "visibility", ["在吗", "最近怎么样", "她话多话少？"],
     "Long-term cross-session visibility: 无 overlay 新 Session 自然召回长期 B"),
    ("C2", "visibility", ["在吗", "她是不是其实话特别少？"],
     "旧信息诱导抵抗（无 overlay）"),
    ("C3", "evolution", ["不对，她其实话特别多。", "她话多话少？"],
     "Same-session correction evolution: B + C(overlay) → C current（非 persistence 证明）"),
    ("C4", "control", ["在吗", "今天天气不错", "你最近在干嘛"],
     "无关闲聊：无 B 内容泄漏/citation"),
    ("C5", "control", ["她平时爱吃什么？"],
     "不同属性：无此 memory，不应拿话痨答/应走 A′ 不确定"),
    ("C6", "control", ["她这个人好相处吗？"],
     "persona correction fixture 隔离：memory 回答不被 persona 纠正污染"),
]


def auto_runtime(fixture, session_overlay, probe_turn, session_state=None):
    """AUTO runtime layer：跑 loader + (F5-e 归约, 若 overlay) + retrieve/support on transient base。"""
    base = load_runtime_persona(fixture, session_overlay or [])
    # F5-e lane info
    lane_info = None
    if session_overlay:
        stmts = []
        for c in fixture.get("corrections") or []:
            if c.get("status") == "active" and c.get("target_kind") == "memory_item" and c.get("corrected_value"):
                stmts.append({"kind": "correction", "value": c["corrected_value"], "id": c["id"],
                              "source_turn": c.get("user_statement"), "at": c.get("created_at"),
                              "target_domain": "memory", "field": c.get("target_path"), "target_id": c.get("target_id")})
        for o in session_overlay:
            stmts.append({"kind": "correction", "value": o["corrected_value"], "id": o["new_claim_id"],
                          "source_turn": o.get("source_turn"), "at": o.get("at"),
                          "target_domain": o.get("target_domain"), "field": o.get("field"),
                          "target_id": o.get("target_id")})
        lanes = f5e.resolve_statements(stmts)
        lane_info = {k: {"current": v["current"], "superseded": v["superseded"],
                         "conflicts": v["conflicts"]} for k, v in lanes.items()}
    active = [{"id": it["id"], "content": it["content"], "correction_id": it.get("correction_id"),
               "target_id": it.get("target_id")}
              for b in base["memory"] for it in base["memory"][b] if it.get("status") == "active"]
    # retrieve on transient base
    import memory_retrieval as mr
    retr = mr.retrieve(base, {}, probe_turn, k=5)
    used = [x["memory"]["id"] for x in retr["items"]]
    # boundary on probe
    fl = rb.check_reality(base, probe_turn, now=datetime(2026, 9, 1))
    fl.update(rb.assess_support(base, probe_turn, retrieved_items=retr["items"],
                                now=datetime(2026, 9, 1), flags=fl))
    return {"projected_corrections": active, "f5e_lanes": lane_info,
            "retrieve_used": used, "boundary_state": fl.get("boundary_state"),
            "boundary_active": fl.get("boundary_active")}


def run_case(fixture, turns, adapter, session_overlay=None, persona_corr_fixture=False):
    pm_before = json.dumps(fixture, ensure_ascii=False, sort_keys=True)
    base = load_runtime_persona(fixture, session_overlay or [])
    gw = LLMGateway(adapter=adapter, model=MODEL)
    rt = PersonaRuntime(persona_memory=base, gateway=gw)
    sid = None
    recs = []
    for i, t in enumerate(turns):
        # AUTO runtime state on this turn's probe
        ar = auto_runtime(fixture, session_overlay, t)
        r = rt.respond(t, session_id=sid)
        if sid is None:
            sid = r["session_update"]["session_id"]
        recs.append({
            "user": t,
            "auto": ar,
            "raw": r["assistant_response"],
            "used_memory": r["used"].get("memory_items", []),
            "boundary_state": r["reality_flags"].get("boundary_state"),
            "corrected_value_used": bool(re.search(r"(话痨|话多|话多话少|特别能说|话匣|能说|话密)", r["assistant_response"])),
            "resists_old": "话少" not in r["assistant_response"] or "不是" in r["assistant_response"] or "记岔" in r["assistant_response"],
            "mechanical": bool(MECH.search(r["assistant_response"])),
            "submissive": bool(SUBM.search(r["assistant_response"])),
        })
    pm_after = json.dumps(fixture, ensure_ascii=False, sort_keys=True)
    return {"records": recs, "pm_bytes_unchanged": pm_before == pm_after}


def main():
    if not os.environ.get("DEEPSEEK_API"):
        print("REAL_LLM_RUN = BLOCKED_BY_MISSING_CREDENTIALS")
        return 0
    os.environ.setdefault("OPENAI_API_KEY", os.environ["DEEPSEEK_API"])
    os.environ.setdefault("OPENAI_BASE_URL", "https://api.deepseek.com")
    try:
        adapter = make_provider_adapter(PROVIDER)
    except RealLLMUnavailable as e:
        print(f"REAL_LLM_RUN = BLOCKED_BY_MISSING_CREDENTIALS: {e}")
        return 0

    run = {"run_id": "stage59b_f5f_cross_" + uuid.uuid4().hex[:10],
           "timestamp": datetime.now().isoformat(timespec="seconds"),
           "provider": PROVIDER, "model": MODEL, "configuration": {"n": 3},
           "results": {}, "privacy": {"api_key_in_output": False}}
    os.makedirs(RESULT_DIR, exist_ok=True)
    for (cid, kind, turns, note) in CASES:
        run["results"][cid] = {"kind": kind, "note": note, "n": 3, "trials": []}
        for i in range(3):
            overlay = None
            if cid == "C3":
                overlay = [{"target_domain": "memory", "field": "memory.core_facts", "target_id": "mi_A",
                            "corrected_value": "她话特别多", "new_claim_id": "mi_C",
                            "source_turn": "用户纠正", "at": "t0"}]
            fx = fixture_pm(extra_persona_corr=(cid == "C6"))
            tr = run_case(fx, turns, adapter, session_overlay=overlay)
            run["results"][cid]["trials"].append(tr)
            print(f"\n===== {cid}#{i} [{kind}] =====")
            for j, rec in enumerate(tr["records"]):
                a = rec["auto"]
                print(f"  U[{j}]: {rec['user']}")
                print(f"  AUTO: active={[p['content'] for p in a['projected_corrections']]} "
                      f"lane_current={[ (l['current']['value'] if l.get('current') else None) for l in (a['f5e_lanes'] or {}).values() ]} "
                      f"used={a['retrieve_used']} boundary={a['boundary_state']}")
                print(f"  A[{j}]: {rec['raw']}")
                print(f"  mark: corr_used={rec['corrected_value_used']} resist={rec['resists_old']} "
                      f"mech={rec['mechanical']} subm={rec['submissive']}")
            print(f"  pm_bytes_unchanged={tr['pm_bytes_unchanged']}")
    out = os.path.join(RESULT_DIR, run["run_id"] + ".json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(run, f, ensure_ascii=False, indent=2)
    print("\nRESULT_FILE:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
