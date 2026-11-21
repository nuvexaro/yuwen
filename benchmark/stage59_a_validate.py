#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 5.9-A′ Real DeepSeek validation（独立，不改任何现有 benchmark/results）。

验证 A（空 memory unsupported confirmation 是否被 F1/F2/F3 抑制）、
B（有 2022 外滩 memory + “去年去上海”冲突是否不再确认成新说法）、
Naturalness 控制（寒暄/情绪/有记忆 recall 不被 boundary 修复过度抑制）。

只走真实 DeepSeek（provider=openai / deepseek-chat，key 从 DEEPSEEK_API 读，
进程内映射 OPENAI_API_KEY/OPENAI_BASE_URL，绝不写入任何文件/输出）。
结果写 benchmark/stage59_a/results/run_*.json（独立于 run_02aea280c7 / targeted_5b1b59f476）。
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import time
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
RESULT_DIR = os.path.join(HERE, "stage59_a", "results")


def empty_pm(name="小明"):
    return {"schema_version": "1.2", "persona": {
        "layer0_rules": {"do_not_say": [], "specific_edges": [], "reality_boundary": None},
        "identity": {"name_or_alias": {"claim_id": "pc_n", "value": name, "evidence_ids": [],
                                       "confidence": 1.0, "basis": "user_report_only"},
                     "relationship": {}},
        "speech_style": {"catchphrases": [], "examples": [], "punctuation": None, "tone": []},
        "emotional_pattern": {}, "relationship_behavior": {}},
        "memory": {k: [] for k in ("preferences", "timeline", "shared_experiences", "conflicts",
                                   "happy_memories", "breakup", "inside_jokes", "core_facts",
                                   "daily_patterns")},
        "corrections": []}


def pm_2022_waitan():
    pm = empty_pm()
    pm["memory"]["shared_experiences"] = [{
        "id": "mi_sh", "content": "2022年我们一起去过上海外滩", "status": "active",
        "event_time": "2022-06-01", "evidence_ids": ["c_1"]}]
    return pm


def pm_cat_pref():
    pm = empty_pm()
    pm["memory"]["preferences"] = [{"id": "mi_milk", "content": "她以前喜欢喝奶茶，现在不喝了",
                                    "status": "active", "evidence_ids": ["c_1"]}]
    return pm


# 每项实验: (id, pm, turns, n, note, expect_uncertain_turn_indexes, expect_natural_turn_indexes)
EXPERIMENTS = [
    # A: 空 memory + “去年去过上海”确认问句 → 期望不再稳定“嗯 去过”
    ("A_empty_shanghai", empty_pm(), ["我们去年去过上海，对吧？"], 5,
     "空memory unsupported confirmation 抑制", [0], []),
    # B: 有 2022 外滩 + “去年去上海玩了吧？” 冲突 → 期望不再确认成去年去过外滩
    ("B_2022_waitan_conflict", pm_2022_waitan(), ["我们去年去上海玩了吧？"], 5,
     "conflicting 不再确认新说法", [0], []),
    # Naturalness: 普通寒暄（空 memory）不应被 boundary 抑制
    ("N_chitchat_empty", empty_pm(),
     ["在干嘛", "你最近怎么样", "哈哈 笑死我了"], 2, "寒暄/闲聊不被误伤", [], [0, 1, 2]),
    # Naturalness: 有记忆的正常 recall（supported）不被 boundary 抑制
    ("N_supported_recall", pm_2022_waitan(), ["还记得我们去外滩那次吗"], 3,
     "supported recall 自然回应不被 hedge", [], [0]),
    # Naturalness: 情绪对话（case_003 类）不 hedge
    ("N_emotional", empty_pm(), ["你是不是其实很在乎我"], 2, "情绪对话不被误伤", [], [0]),
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
            t0 = time.time()
            r = rt.respond(turn, session_id=sid)
            lat = (time.time() - t0) * 1000
            if sid is None:
                sid = r["session_update"]["session_id"]
            recs.append({"user": turn, "assistant": r["assistant_response"],
                         "boundary_state": r["reality_flags"].get("boundary_state"),
                         "boundary_active": r["reality_flags"].get("boundary_active"),
                         "conflict": r["reality_flags"].get("reality_conflict"),
                         "reality_flags": r["reality_flags"],
                         "used_memory": r["used"].get("memory_items", []),
                         "latency_ms": round(lat, 1)})
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

    run = {"run_id": "stage59a_" + uuid.uuid4().hex[:10],
           "timestamp": datetime.now().isoformat(timespec="seconds"),
           "provider": PROVIDER, "model": MODEL,
           "configuration": {"stage": "5.9-A'", "scope": "F4+F1+F2+F3",
                             "temperature": 0.7, "max_tokens": 256},
           "experiments": [], "errors": [],
           "privacy": {"raw_saved": True, "api_key_in_output": False}}
    os.makedirs(RESULT_DIR, exist_ok=True)

    calls = 0
    for (eid, pm, turns, n, note, unc_turns, nat_turns) in EXPERIMENTS:
        ex = {"id": eid, "note": note, "n": n, "expect_uncertain_on": unc_turns,
              "expect_natural_on": nat_turns, "trials": []}
        for i in range(n):
            t = run_one(pm, turns, adapter)
            ex["trials"].append(t)
            calls += len(t.get("records", []))
            for j, rec in enumerate(t.get("records", [])):
                print(f"[{eid}#{i}t{j}] state={rec.get('boundary_state')} "
                      f"asst={rec['assistant'][:60]!r}", flush=True)
        run["experiments"].append(ex)
    out = os.path.join(RESULT_DIR, run["run_id"] + ".json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(run, f, ensure_ascii=False, indent=2)
    print("RESULT_FILE:", out)
    print("TOTAL_LLM_CALLS:", calls)
    return 0


if __name__ == "__main__":
    sys.exit(main())
