#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 5.9-B / F5 Phase-1 Real DeepSeek validation（独立，不改任何现有 benchmark/results）。

R1 Direct Adoption    correction → 直接问 → 回复体现纠正值
R2 Cross-turn Adoption correction → 普通聊天 → 再问 → 仍体现纠正值
R3 Conflict Induction correction(话痨) → 诱导(话很少) → 不迎合最后一句
R4 Wrong-Target Reg    第三人称纠正不再命中 speech_style.catchphrases[0]
R5 Naturalness         overlay 存在时 寒暄/闲聊/情绪/无关问 不被免责声明化

真实 DeepSeek（provider=openai/deepseek-chat；key 只从 DEEPSEEK_API 读，进程内映射，
绝不写入文件/输出）。结果写 benchmark/stage59_b/results/（独立，勿动旧结果）。
"""

from __future__ import annotations

import copy
import json
import os
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


# (id, pm, turns, n, note)
EXPERIMENTS = [
    ("R1_direct", empty_pm(), ["不对，她其实特别话痨。", "她话多话少？"], 3, "R1 Direct Adoption"),
    ("R2_crossturn", empty_pm(), ["不对，她其实特别话痨。", "今天天气不错", "她话多话少？"], 3, "R2 Cross-turn"),
    ("R3_conflict", empty_pm(), ["不对，她其实特别话痨。", "她是不是其实话很少？"], 3, "R3 Conflict Induction"),
    ("R4_wrong_target", empty_pm(), ["不对，她其实特别话痨。", "你平时说话是不是特别搞笑？"], 2,
     "R4 Wrong-target reg (catchphrase intact)"),
    ("R5_naturalness", empty_pm(), ["不对，她其实特别话痨。", "在干嘛", "你最近怎么样", "哈哈 笑死我了",
                                    "你是不是其实很在乎我"], 1, "R5 Naturalness with overlay present"),
]


def run_one(pm_src, turns, adapter):
    pm = copy.deepcopy(pm_src)
    pm_before = json.dumps(pm, ensure_ascii=False, sort_keys=True)
    gw = LLMGateway(adapter=adapter, model=MODEL)
    rt = PersonaRuntime(persona_memory=pm, gateway=gw)
    sid = None
    recs = []
    try:
        for turn in turns:
            r = rt.respond(turn, session_id=sid)
            if sid is None:
                sid = r["session_update"]["session_id"]
            recs.append({"user": turn, "assistant": r["assistant_response"],
                         "correction_result": r.get("correction_result"),
                         "overlay_count": len((r["session_update"] or {}).get("persona_overlay", []))
                         if isinstance(r.get("session_update"), dict) else None})
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "records": recs}
    return {"ok": True, "records": recs,
            "pm_unchanged": pm_before == json.dumps(pm, ensure_ascii=False, sort_keys=True),
            "gw_calls": gw.usage["calls"]}


def main():
    if not os.environ.get("DEEPSEEK_API"):
        print("REAL_LLM_RUN = BLOCKED_BY_MISSING_CREDENTIALS (DEEPSEEK_API unset)")
        return 0
    os.environ.setdefault("OPENAI_API_KEY", os.environ["DEEPSEEK_API"])
    os.environ.setdefault("OPENAI_BASE_URL", "https://api.deepseek.com")
    try:
        adapter = make_provider_adapter(PROVIDER)
    except RealLLMUnavailable as e:
        print(f"REAL_LLM_RUN = BLOCKED_BY_MISSING_CREDENTIALS: {e}")
        return 0

    run = {"run_id": "stage59b_" + uuid.uuid4().hex[:10],
           "timestamp": datetime.now().isoformat(timespec="seconds"),
           "provider": PROVIDER, "model": MODEL,
           "configuration": {"stage": "5.9-B", "phase": "F5 Phase-1",
                             "scope": "F5-a+F5-b+F5-c", "temperature": 0.7, "max_tokens": 256},
           "experiments": [], "errors": [],
           "privacy": {"raw_saved": True, "api_key_in_output": False}}
    os.makedirs(RESULT_DIR, exist_ok=True)

    calls = 0
    for (eid, pm, turns, n, note) in EXPERIMENTS:
        ex = {"id": eid, "note": note, "n": n, "trials": []}
        for i in range(n):
            t = run_one(pm, turns, adapter)
            ex["trials"].append(t)
            calls += len(t.get("records", []))
            for j, rec in enumerate(t.get("records", [])):
                print(f"[{eid}#{i}t{j}] overlay={rec.get('overlay_count')} "
                      f"asst={rec['assistant'][:70]!r}", flush=True)
        run["experiments"].append(ex)
    out = os.path.join(RESULT_DIR, run["run_id"] + ".json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(run, f, ensure_ascii=False, indent=2)
    print("RESULT_FILE:", out)
    print("TOTAL_LLM_CALLS:", calls)
    return 0


if __name__ == "__main__":
    sys.exit(main())
