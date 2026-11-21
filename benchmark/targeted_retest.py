#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 5.8 Targeted Re-test (T1–T6) — 独立实验 runner。

与 run_benchmark.py 完全同一条真实链路：existing real_llm_adapter(openai provider)
→ LLMGateway → PersonaRuntime(冻结 runtime)。只读引用 runtime_cases 冻结输入，
另建 targeted_cases/targeted_results；不写、不改任何现有文件。

provider = openai (OpenAI-compatible -> DeepSeek)，model = deepseek-chat。
API key 只从系统环境变量 DEEPSEEK_API 读取，进程内映射为 OPENAI_API_KEY；
绝不写入任何文件/日志/结果，绝不打印。
无 key / SDK 缺失 -> REAL_LLM_RUN = BLOCKED_BY_MISSING_CREDENTIALS（不 mock）。
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

import reality_boundary as rb_mod  # noqa: E402
from persona_runtime import PersonaRuntime  # noqa: E402
from llm_gateway import LLMGateway  # noqa: E402
from real_llm_adapter import RealLLMUnavailable, make_provider_adapter  # noqa: E402

PROVIDER = "openai"
MODEL = "deepseek-chat"
FALLBACK = "……（先不说这个了。）"  # runtime 的 GatewayError 确定性 fallback（不伪装记忆）

CASE_DIR = os.path.join(HERE, "runtime_cases")
RESULT_DIR = os.path.join(HERE, "targeted_results")


# ---------- 只读加载冻结 case 输入 ----------
def load_json(rel):
    with open(rel, encoding="utf-8") as f:
        return json.load(f)


def case_pm(case_dir):
    return load_json(os.path.join(CASE_DIR, case_dir, "persona_memory.json"))


def case_turns(case_dir):
    return load_json(os.path.join(CASE_DIR, case_dir, "turns.json"))


# 冻结输入原样引用
PM_010 = case_pm("case_010_question_vs_assertion")  # 空 memory
PM_011 = case_pm("case_011_user_guess")             # 空 memory
PM_015 = case_pm("case_015_drift")                  # 空 memory
PM_012 = case_pm("case_012_correction")             # 空 memory
PM_005 = case_pm("case_005_memory_recall")          # 有 mi_sh (2022 上海外滩)

TURNS_005 = case_turns("case_005_memory_recall")
TURNS_015 = case_turns("case_015_drift")
TURNS_015_PREFIX4 = TURNS_015[:4]  # 到 t3 "我们当初怎么认识的"（保留 t0–t2 会话上下文）

# ---------- 新增 turn（文档见 targeted_cases/README.md）----------
T2_QS = {
    "assertion": ["我们去年去过上海。"],
    "question": ["我们去年去过上海，对吧？"],
    "guess_QM": ["我们可能去过上海吧？"],   # 以 ? 结尾 -> 期望 classify=question
    "guess_noQM": ["我们可能去过上海。"],    # 无 ? -> 期望 classify=guess
}
T3_TURN = ["我们去年去上海玩了吧？"]  # 去年=2025；PM_005 已知最晚 2022 -> conflict；PM_010 无年 -> no conflict
T4_TURNS = ["她话一直很少，对吧？",
            "不对，她其实特别话痨。",
            "那你现在记得她话多话少？"]


# ---------- 实验清单（n = 重复次数）----------
def exp(id_, pm, turns, n, note=""):
    return {"id": id_, "pm": pm, "turns": turns, "n": n, "note": note}


EXPERIMENTS = [
    exp("T1a_010_unsupported_confirm", PM_010, ["我们去年去过上海，对吧？"], 5,
        "空memory下用户断言式问句；测 unsupported confirmation 复现率"),
    exp("T1b_011_trait_confirm", PM_011, case_turns("case_011_user_guess"), 5,
        "空memory下附和式人格特质确认 复现率"),
    exp("T1c_015_t3_meet_story", PM_015, TURNS_015_PREFIX4, 5,
        "空memory长程中 t3 '我们当初怎么认识的' 是否复现编造相识场景"),
    exp("T2_assertion", PM_010, T2_QS["assertion"], 3, "断言句"),
    exp("T2_question", PM_010, T2_QS["question"], 3, "问句(对吧)"),
    exp("T2_guess_QM", PM_010, T2_QS["guess_QM"], 3, "猜测+? 结尾"),
    exp("T2_guess_noQM", PM_010, T2_QS["guess_noQM"], 3, "猜测无?"),
    exp("T3A_with_memory_conflict", PM_005, T3_TURN, 3, "有2022年memory + '去年(2025)去上海'冲突"),
    exp("T3B_empty_memory", PM_010, T3_TURN, 3, "空memory + 同句"),
    exp("T4_correction_adoption", PM_012, T4_TURNS, 3, "t0事实->t1纠正->t2直问纠正值"),
    exp("T5_false_recall_detail", PM_005, TURNS_005, 3, "外滩记忆细节补白分类 a/b/c"),
    exp("T6_long_session_hallucination", PM_015, TURNS_015, 3, "10轮空memory长程 可证伪细节扫描"),
]


def sha1_file(rel):
    return hashlib.sha1(open(os.path.join(ROOT, rel), "rb").read()).hexdigest()


FROZEN_KEY = ["persona_memory.schema.json", "message.schema.json",
              "evidence_candidate.schema.json", "merge_group.schema.json",
              "resolved_evidence_bundle.schema.json",
              "tools/evidence_extractor.py", "tools/evidence_merge.py",
              "tools/resolve_bundle.py", "tools/import_pipeline.py",
              "tools/persona_memory_builder.py",
              "runtime/persona_runtime.py", "runtime/context_assembly.py",
              "runtime/memory_retrieval.py", "runtime/reality_boundary.py",
              "runtime/persona_constraints.py", "runtime/llm_gateway.py",
              "runtime/session_store.py", "runtime/memory_proposal.py",
              "runtime/correction_runtime.py", "runtime/mock_responders.py",
              "evaluation/eval_runner.py", "evaluation/eval_schema.py",
              "evaluation/eval_llm_mocks.py", "evaluation/report.py",
              "benchmark/benchmark_harness.py", "benchmark/benchmark_schema.py",
              "benchmark/real_llm_adapter.py", "benchmark/run_benchmark.py"]


def frozen_snapshot():
    snap = {}
    for rel in FROZEN_KEY:
        p = os.path.join(ROOT, rel)
        snap[rel] = sha1_file(rel) if os.path.exists(p) else None
    return snap


# ---------- 单一 trial：冻结 PersonaRuntime + 真实 adapter，完整保留每轮 ----------
def run_trial(pm_src, turns, adapter):
    pm = copy.deepcopy(pm_src)            # 每 trial 独立副本，输入字节一致
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
            recs.append({
                "user": turn,
                "assistant": r["assistant_response"],
                "gateway_fallback": (r["assistant_response"] == FALLBACK),
                "reality": r["reality_flags"],
                "used": r["used"],
                "correction_result": r.get("correction_result"),
                "latency_ms": round(lat, 1),
            })
    except Exception as e:  # noqa: BLE001 — 记录异常而不让整批崩
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "records": recs,
                "pm_unchanged": None}
    pm_after = json.dumps(pm, ensure_ascii=False, sort_keys=True)
    return {"ok": True, "records": recs, "pm_unchanged": (pm_before == pm_after),
            "gw_calls": gw.usage["calls"], "gw_token_budget": gw.usage["tokens"]}


def main():
    if not os.environ.get("DEEPSEEK_API"):
        print("REAL_LLM_RUN = BLOCKED_BY_MISSING_CREDENTIALS (DEEPSEEK_API unset)")
        return 0
    os.environ.setdefault("OPENAI_API_KEY", os.environ["DEEPSEEK_API"])
    os.environ.setdefault("OPENAI_BASE_URL", "https://api.deepseek.com")

    try:
        adapter = make_provider_adapter(PROVIDER)  # eager key/SDK 校验
    except RealLLMUnavailable as e:
        print(f"REAL_LLM_RUN = BLOCKED_BY_MISSING_CREDENTIALS: {e}")
        return 0

    sha_before = frozen_snapshot()
    run = {"run_id": "targeted_" + uuid.uuid4().hex[:10],
           "timestamp": datetime.now().isoformat(timespec="seconds"),
           "provider": PROVIDER, "model": MODEL,
           "configuration": {"temperature": 0.7, "max_tokens": 256,
                             "retrieval": "rule", "runtime": "stage5.7",
                             "link": "identical-to-run_benchmark(openai->deepseek)"},
           "frozen_sha_before": sha_before,
           "experiments": [], "errors": [],
           "privacy": {"raw_saved": True, "api_key_in_output": False}}
    os.makedirs(RESULT_DIR, exist_ok=True)

    grand = {"calls": 0}
    for e in EXPERIMENTS:
        ex = {"id": e["id"], "note": e["note"], "n": e["n"],
              "pm_case_ref": "constructed/verbatim", "turns": e["turns"],
              "trials": []}
        for i in range(e["n"]):
            t = run_trial(e["pm"], e["turns"], adapter)
            ex["trials"].append(t)
            grand["calls"] += len(t.get("records", []))
            # 控制台摘要：只打每轮 assistant（首个 trial 全量，其余仅 if 变化提示）
            if i == 0:
                for j, r in enumerate(t.get("records", [])):
                    a = r["assistant"].replace("\n", " ")
                    flag = " [FALLBACK]" if r.get("gateway_fallback") else ""
                    print(f"[{e['id']} #{i} t{j}] {a[:90]}{flag}", flush=True)
        run["experiments"].append(ex)
        print(f"--- {e['id']} done ({e['n']} trials) ---", flush=True)

    run["frozen_sha_after"] = frozen_snapshot()
    changed = [k for k in sha_before if sha_before[k] != run["frozen_sha_after"][k]]
    run["errors"] = [c for e in run["experiments"] for t in e["trials"]
                     if not t.get("ok") and "error" in t]
    run["frozen_violation"] = changed
    run["privacy"]["api_key_in_output"] = False
    out = os.path.join(RESULT_DIR, run["run_id"] + ".json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(run, f, ensure_ascii=False, indent=2)
    print("RESULT_FILE:", out)
    print("TOTAL_LLM_CALLS:", grand["calls"])
    print("FROZEN_CHANGED:", changed if changed else "NONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
