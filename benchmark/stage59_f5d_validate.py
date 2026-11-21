#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 5.9-B / F5-d Real-LLM Validation（独立，不改任何 runtime/benchmark/results）。

覆盖：
  R-D4-1 Direct correction → later direct recall
  R-D4-2 Cross-topic recall（≥2 无关主题 + paraphrase）
  R-D4-3 Long-session recall（≥6 无关 turn + 非原句询问）
  R-D4-4 Conflict resistance
  R-D4-5 Persona contamination（persona correction 不进入 memory retrieval）
  R-D4-6 Naturalness / mechanical recall（观察，作为独立维度）

真实 DeepSeek。结果写 benchmark/stage59_b/results/（stage59b_f5d_*.json）。
每 probe 记录完整 turns、assistant、correction_result、session overlay、used_memory。
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


# 核心场景脚本：(id, note, turns 序列)
# correction 句含 “她/他” → memory-domain；含 “我” 说话风格 → persona-domain（供 contamination 对照）
SCENARIOS = [
    ("R-D4-1a", "direct recall 立即问",
     ["不对，她其实特别话痨。", "她话多话少？"]),
    ("R-D4-1b", "direct recall 稍换问法",
     ["不对，她其实特别话痨。", "她平时说话多吗？"]),
    ("R-D4-2a", "cross-topic: 2 无关主题 + paraphrase",
     ["不对，她其实特别话痨。", "今天天气真热", "你周末干嘛了", "她是不是特别能聊？"]),
    ("R-D4-2b", "cross-topic 变体",
     ["她以前是不是特别不爱说话？", "不对，她其实话痨，话特别多。", "晚饭吃啥好", "我看球去了", "她话多不多啊？"]),
    ("R-D4-3a", "long-session ≥6 unrelated turns + 非原句",
     ["不对，她其实特别话痨。", "在吗", "今天好累", "你玩游戏吗", "天气怎么样", "吃了吗", "周末有啥计划", "你觉得她好相处吗？"]),
    ("R-D4-3b", "long-session 变体",
     ["她其实特别话痨。", "早安", "刚下班", "晚上吃啥", "有点困", "明天要上班", "你睡了吗", "她这人怎么样？"]),
    ("R-D4-4a", "conflict: correction + 后续矛盾诱导",
     ["不对，她其实特别话痨。", "她是不是其实话特别少啊？"]),
    ("R-D4-4b", "conflict: correction + 后续普通 assertion(不自变事实)",
     ["不对，她其实特别话痨。", "我猜她话挺少的", "她话多话少？"]),
    ("R-D4-5a", "persona contamination: 对'我'的 correction 不得进 memory",
     ["不对，我其实话很少。", "我平时话多吗？"]),
    ("R-D4-6a", "naturalness/mechanical observation",
     ["不对，她其实特别话痨。", "在干嘛", "她话多话少？"]),
]


def run_one(pm_src, turns, adapter):
    pm = copy.deepcopy(pm_src)
    pm_before = json.dumps(pm, ensure_ascii=False, sort_keys=True)
    gw = LLMGateway(adapter=adapter, model=MODEL)
    rt = PersonaRuntime(persona_memory=pm, gateway=gw)
    sid = None
    recs = []
    for t in turns:
        r = rt.respond(t, session_id=sid)
        if sid is None:
            sid = r["session_update"]["session_id"]
        recs.append({
            "user": t,
            "assistant": r["assistant_response"],
            "boundary_state": r["reality_flags"].get("boundary_state"),
            "boundary_active": r["reality_flags"].get("boundary_active"),
            "category": r["reality_flags"].get("user_category"),
            "correction_result": r.get("correction_result"),
            "overlay_count": len((r["session_update"] or {}).get("persona_overlay", []))
            if isinstance(r.get("session_update"), dict) else 0,
            "used_memory": r["used"].get("memory_items", []),
            "latency_ms": round((r["session_update"] or {}).get("x", 0) or 0, 0),
        })
    return {"ok": True, "records": recs,
            "pm_unchanged": pm_before == json.dumps(pm, ensure_ascii=False, sort_keys=True)}


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

    run = {"run_id": "stage59b_f5d_" + uuid.uuid4().hex[:10],
           "timestamp": datetime.now().isoformat(timespec="seconds"),
           "provider": PROVIDER, "model": MODEL,
           "configuration": {"stage": "5.9-B", "phase": "F5-d real-LLM validation"},
           "scenarios": [], "privacy": {"raw_saved": True, "api_key_in_output": False}}
    os.makedirs(RESULT_DIR, exist_ok=True)

    calls = 0
    for (sid, note, turns) in SCENARIOS:
        t = run_one(empty_pm(), turns, adapter)
        calls += len(t["records"])
        run["scenarios"].append({"id": sid, "note": note, "turns": turns,
                                 "records": t["records"], "pm_unchanged": t["pm_unchanged"]})
        print(f"\n===== {sid} ({note}) =====")
        for j, rec in enumerate(t["records"]):
            crr = rec.get("correction_result")
            crs = f" target_domain={crr.get('target_domain')} new_id={crr.get('new_claim_id')}" if crr else ""
            print(f"  U[{j}]: {rec['user']}  [{rec['category']}|{rec.get('boundary_state')}|overlay={rec['overlay_count']}]{crs}")
            print(f"  A[{j}]: {rec['assistant']}")
    out = os.path.join(RESULT_DIR, run["run_id"] + ".json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(run, f, ensure_ascii=False, indent=2)
    print("\nRESULT_FILE:", out)
    print("TOTAL_LLM_CALLS:", calls)
    return 0


if __name__ == "__main__":
    sys.exit(main())
