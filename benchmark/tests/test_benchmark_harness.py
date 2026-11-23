#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Benchmark Harness 测试（Stage 5.8，15 项）。

mock 全绿；real adapter 缺 key → BLOCKED；验证 key 不入日志/result；
frozen SHA 不变；不改冻结文件。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import shutil
import hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
BENCH = os.path.dirname(HERE)
ROOT = os.path.dirname(BENCH)
for p in (BENCH, os.path.join(ROOT, "runtime"), os.path.join(ROOT, "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

import benchmark_harness as bh  # noqa: E402
import benchmark_schema as bs  # noqa: E402
import real_llm_adapter as rla  # noqa: E402


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


def all_cases():
    d = os.path.join(BENCH, "runtime_cases")
    return [os.path.join(d, x) for x in sorted(os.listdir(d))
            if os.path.isdir(os.path.join(d, x)) and x.startswith("case_")]


# ---- 1 mock adapter ----
def t_mock_adapter():
    r = bh.run_case(bh.load_case(all_cases()[0]), provider="mock")
    C.ok("1: mock case runs", r["status"] == "PASS", r.get("error"))
    C.ok("1: latency recorded", isinstance(r["latency_ms"], (int, float)))


# ---- 2 real adapter missing key ----
def t_real_adapter_missing_key():
    # 移除 key 环境 → BLOCKED
    os.environ.pop("ANTHROPIC_API_KEY", None)
    os.environ.pop("OPENAI_API_KEY", None)
    case = bh.load_case(all_cases()[0])
    for prov in ("anthropic", "openai"):
        try:
            cr = bh.run_case(case, provider=prov)
            C.ok(f"2: {prov} no-key → BLOCKED", cr["status"] == "BLOCKED"
                 and "BLOCKED" in (cr.get("error") or ""), str(cr.get("error")))
        except rla.RealLLMUnavailable:
            C.ok(f"2: {prov} no-key raises → ok", True)


# ---- 3 API key not in logs/results ----
def t_key_not_leaked():
    case = bh.load_case(all_cases()[0])
    os.environ["ANTHROPIC_API_KEY"] = "sk-SECRETTEST123"
    try:
        # anthropic SDK 未装 → RealLLMUnavailable，但 key 不该出现在任何输出
        cr = bh.run_case(case, provider="anthropic")
        blob = json.dumps(cr, ensure_ascii=False)
        C.ok("3: key not in case result", "SECRETTEST123" not in blob)
    except Exception as e:
        C.ok("3: exception safe (no key leak)", "SECRETTEST123" not in str(e))
    finally:
        os.environ.pop("ANTHROPIC_API_KEY", None)


# ---- 4 provider selection ----
def t_provider_selection():
    # 无 key → eager 抛 RealLLMUnavailable（正确的 BLOCKED 行为）
    os.environ.pop("ANTHROPIC_API_KEY", None)
    os.environ.pop("OPENAI_API_KEY", None)
    for prov in ("anthropic", "openai"):
        try:
            rla.make_provider_adapter(prov)
            C.ok(f"4: {prov} should raise without key", False)
        except rla.RealLLMUnavailable:
            C.ok(f"4: {prov} raises RealLLMUnavailable (selection validated)", True)
    try:
        rla.make_provider_adapter("nope")
        C.ok("4: unknown provider raises", False)
    except rla.RealLLMUnavailable as e:
        C.ok("4: unknown provider raises", "未知 provider" in str(e), str(e))


# ---- 5 timeout/retry 在 gateway 已测；这里测 adapter 无 key 快速失败 ----
def t_timeout_retry_path():
    # gateway 层 retry 已由 runtime test 覆盖；此处确认 harness 不吞 RealLLMUnavailable 成伪 pass
    os.environ.pop("OPENAI_API_KEY", None)
    cr = bh.run_case(bh.load_case(all_cases()[0]), provider="openai")
    C.ok("5: openai no-key not fake pass", cr["status"] == "BLOCKED", cr.get("error"))


# ---- 6 case loading ----
def t_case_loading():
    d = all_cases()[0]
    case = bh.load_case(d)
    C.ok("6: case loads meta/pm/turns", {"meta", "persona_memory", "turns"} <= set(case.keys()))
    C.ok("6: persona_memory has persona+memory", "persona" in case["persona_memory"]
         and "memory" in case["persona_memory"])
    C.ok("6: turns non-empty", len(case["turns"]) > 0)


# ---- 7 result schema ----
def t_result_schema():
    run = bh.run_dataset(all_cases(), provider="mock")
    for k in ("run_id", "status", "provider", "model", "cases",
              "aggregate_auto_metrics", "errors"):
        C.ok(f"7: run has {k}", k in run)
    C.ok("7: run status COMPLETED", run["status"] == "COMPLETED", run["status"])
    C.ok("7: cases populated", len(run["cases"]) >= 15)
    c0 = run["cases"][0]
    for k in ("case_id", "status", "auto", "latency_ms", "provider"):
        C.ok(f"7: case has {k}", k in c0)


# ---- 8 AUTO metrics ----
def t_auto_metrics():
    run = bh.run_dataset(all_cases(), provider="mock")
    agg = run["aggregate_auto_metrics"]
    C.ok("8: aggregate has counts", agg["case_count"] >= 15 and agg["pass"] == agg["case_count"])
    C.ok("8: correction rate present or None", "correction_overlay_rate" in agg)


# ---- 9 correction evaluation ----
def t_correction_eval():
    d = [x for x in all_cases() if "correction" in x][0]
    cr = bh.run_case(bh.load_case(d), provider="mock")
    C.ok("9: correction overlay ok", cr["auto"].get("correction_overlay_ok") is True, str(cr["auto"]))
    C.ok("9: new id stable", cr["auto"].get("correction_new_id_stable") is True)


# ---- 10 reality evaluation ----
def t_reality_eval():
    # case_006 期望 no-conflict（已知限制）；造一个真的 year-conflict case 单独测
    pm = {"schema_version": "1.2", "revision": 1,
          "persona": {"layer0_rules": {"do_not_say": [], "specific_edges": [], "reality_boundary": None},
                      "identity": {"name_or_alias": {"claim_id": "pc_n", "value": "小明", "evidence_ids": [],
                                                     "confidence": 1.0, "basis": "user_report_only"},
                                   "relationship": {}},
                      "speech_style": {"catchphrases": [], "examples": []},
                      "emotional_pattern": {}, "relationship_behavior": {}},
          "memory": {"shared_experiences": [{"id": "mi_2022sh", "content": "2022年我们去过上海",
                                             "status": "active"}],
                     **{b: [] for b in ("preferences", "timeline", "conflicts", "happy_memories",
                                        "breakup", "inside_jokes", "core_facts", "daily_patterns")}},
          "corrections": []}
    case = {"meta": {"case_id": "cx", "name_or_alias": "小明"}, "persona_memory": pm,
            "turns": ["我们去年去上海了吗？"], "expected": {"reality_conflict_on_turn": [0]}}
    cr = bh.run_case(case, provider="mock")
    C.ok("10: year-conflict detected", cr["auto"].get("reality_conflict_detected") is True, str(cr["auto"]))


# ---- 11 retrieval P/R ----
def t_retrieval_pr():
    # runtime retrieval 无外部 ground-truth 注入；此处验证 provenance_memory 记录存在
    d = [x for x in all_cases() if "memory_recall" in x][0]
    cr = bh.run_case(bh.load_case(d), provider="mock")
    C.ok("11: provenance memory recorded (recall case)", "mi_sh" in cr["auto"].get("provenance_memory", []),
         str(cr["auto"].get("provenance_memory")))


# ---- 12 privacy raw disabled ----
def t_privacy():
    run = bh.run_dataset(all_cases()[:3], provider="mock")  # 默认不存 raw
    C.ok("12: privacy raw_saved False", run["privacy"]["raw_saved"] is False)
    C.ok("12: response_ref is hash (not raw)", isinstance(run["cases"][0]["response_ref"], list)
         and all(len(x) == 16 for x in run["cases"][0]["response_ref"]),
         str(run["cases"][0]["response_ref"])[:40])
    # save-raw=True 时存文本但不存 key
    run2 = bh.run_dataset(all_cases()[:1], provider="mock", save_raw=True)
    C.ok("12: save-raw marks True", run2["privacy"]["raw_saved"] is True)


# ---- 13 determinism (mock) ----
def t_determinism_mock():
    outs = set()
    for _ in range(3):
        r = bh.run_case(bh.load_case(all_cases()[0]), provider="mock")
        outs.add(json.dumps({k: r[k] for k in ("auto", "latency_ms") if k != "latency_ms"},
                            ensure_ascii=False, sort_keys=True))
    C.ok("13: mock deterministic", len(outs) == 1, str(outs))


# ---- 14 frozen SHA verification ----
def t_frozen_sha():
    expected = {"persona_memory.schema.json": "27750ee4ace4",
                "message.schema.json": "f0224e7a9697",
                "tools/evidence_extractor.py": "3c3063dbfe04",
                "tools/persona_memory_builder.py": None,   # 只测存在
                # Stage 5.9 runtime re-baseline 记录（历史锚点保留）:
                #   Stage 5.8           persona_runtime.py = 554bef410f7a
                #   Stage 5.9-A(F2/F3)   persona_runtime.py = a894dd7a8efd
                #   Stage 5.9-B(F5)      persona_runtime.py = adcf73d14a71
                #   Stage 5.9-B(F5-dD3)   persona_runtime.py = 85b335fb9876
                #   Stage 6.1(fail-obsv) persona_runtime.py = bba7079012df
                #   v0.3.0(no-fabrication) persona_runtime.py = c4b1b14c560f  ← 当前（authorized reopen）
                "runtime/persona_runtime.py": "c4b1b14c560f"}
    sha = bh.frozen_sha()
    C.ok("14: frozen files have hashes", all(f in sha for f in expected))
    C.ok("14: core frozen match", sha["persona_memory.schema.json"][:12] == "27750ee4ace4")
    C.ok("14: runtime persona_runtime match", sha["runtime/persona_runtime.py"][:12] == "c4b1b14c560f")


# ---- 15 no modification of frozen files ----
def t_no_frozen_mod():
    fb = bh.frozen_sha()
    bh.run_dataset(all_cases(), provider="mock", frozen_before=fb)
    after = bh.frozen_sha()
    C.ok("15: frozen unchanged after run", fb == after)


def main():
    print("=== Benchmark Harness 测试 (Stage 5.8) ===")
    tests = [
        ("1 mock adapter", t_mock_adapter),
        ("2 real adapter missing key", t_real_adapter_missing_key),
        ("3 key not leaked", t_key_not_leaked),
        ("4 provider selection", t_provider_selection),
        ("5 timeout/retry path", t_timeout_retry_path),
        ("6 case loading", t_case_loading),
        ("7 result schema", t_result_schema),
        ("8 AUTO metrics", t_auto_metrics),
        ("9 correction eval", t_correction_eval),
        ("10 reality eval", t_reality_eval),
        ("11 retrieval P/R", t_retrieval_pr),
        ("12 privacy", t_privacy),
        ("13 determinism", t_determinism_mock),
        ("14 frozen SHA", t_frozen_sha),
        ("15 no frozen mod", t_no_frozen_mod),
    ]
    for name, fn in tests:
        print(f"\n▶ {name}")
        try:
            fn()
        except Exception as e:
            import traceback
            C.ok(name, False, f"{type(e).__name__}: {e}")
            traceback.print_exc()
    print(f"\n通过 {C.ok_n} / 失败 {C.fail_n}")
    for f in C.fails:
        print("  -", f)
    sys.exit(0 if C.fail_n == 0 else 1)


if __name__ == "__main__":
    main()
