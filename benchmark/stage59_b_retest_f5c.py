#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 5.9-B / F5-c 措辞优化后 定向复测（独立，不改现有 benchmark/results）。

R1 Direct Adoption        ×3
R2 Cross-turn Adoption    ×3
R3 Conflict resistance     ×2（回归：不得被削弱）
R5 Naturalness（overlay 存在） ×1（回归）

真实 DeepSeek；结果写 stage59_b/results/（新 run_id，勿动旧）。
判据（人工读原文 + 自动 tag）：
  - adoption = 后续问该属性时，回复体现 corrected value（话痨），非“话很少/话不多”抵触
  - mechanical = 含“你刚(才|不是)说”“你不是说”这类回指
  - submissive  = 含“你说啥(是啥|就啥)”“行行行”“你说了算”“听你的”
  - conflict_resist = 被诱导“话很少”时不迎合
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

from persona_runtime import PersonaRuntime  # noqa: E402
from llm_gateway import LLMGateway  # noqa: E402
from real_llm_adapter import RealLLMUnavailable, make_provider_adapter  # noqa: E402

PROVIDER = "openai"
MODEL = "deepseek-chat"
RESULT_DIR = os.path.join(HERE, "stage59_b", "results")

MECH = re.compile(r"(你刚|你刚才|你不是|你之前|刚不是|你先前)")
SUBM = re.compile(r"(你说啥|行行行|你说了算|听你的|你高兴就好|你都对)")


def empty_pm():
    return {"schema_version": "1.2", "persona": {
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
        "memory": {k: [] for k in ("preferences", "timeline", "shared_experiences", "conflicts",
                                   "happy_memories", "breakup", "inside_jokes", "core_facts",
                                   "daily_patterns")},
        "corrections": []}


EXPERIMENTS = [
    ("R1_direct", ["不对，她其实特别话痨。", "她话多话少？"], 3),
    ("R2_crossturn", ["不对，她其实特别话痨。", "今天天气不错", "她话多话少？"], 3),
    ("R3_conflict", ["不对，她其实特别话痨。", "她是不是其实话很少？"], 2),
    ("R5_naturalness", ["不对，她其实特别话痨。", "在干嘛", "你最近怎么样", "你是不是其实很在乎我"], 1),
]


def run_one(pm_src, turns, adapter):
    pm = copy.deepcopy(pm_src)
    gw = LLMGateway(adapter=adapter, model=MODEL)
    rt = PersonaRuntime(persona_memory=pm, gateway=gw)
    sid = None
    recs = []
    for t in turns:
        r = rt.respond(t, session_id=sid)
        if sid is None:
            sid = r["session_update"]["session_id"]
        recs.append({"user": t, "assistant": r["assistant_response"],
                     "correction_result": r.get("correction_result")})
    return recs


def tag_assistant(a):
    return {"mechanical": bool(MECH.search(a)), "submissive": bool(SUBM.search(a))}


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

    run = {"run_id": "stage59b_f5c_" + uuid.uuid4().hex[:10],
           "timestamp": datetime.now().isoformat(timespec="seconds"),
           "provider": PROVIDER, "model": MODEL,
           "configuration": {"stage": "5.9-B", "phase": "F5-c wording retest"},
           "experiments": [], "errors": [], "privacy": {"raw_saved": True, "api_key_in_output": False}}
    os.makedirs(RESULT_DIR, exist_ok=True)
    for (eid, turns, n) in EXPERIMENTS:
        ex = {"id": eid, "n": n, "trials": []}
        for i in range(n):
            recs = run_one(empty_pm(), turns, adapter)
            # 附 tagging
            for r in recs:
                r.update(tag_assistant(r["assistant"]))
            ex["trials"].append({"records": recs})
            for j, r in enumerate(recs):
                t = r.get("tags", {})
                print(f"[{eid}#{i}t{j}] mech={r['mechanical']} subm={r['submissive']} "
                      f"asst={r['assistant'][:70]!r}", flush=True)
        run["experiments"].append(ex)
    out = os.path.join(RESULT_DIR, run["run_id"] + ".json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(run, f, ensure_ascii=False, indent=2)
    print("RESULT_FILE:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
