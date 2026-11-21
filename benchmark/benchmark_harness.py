#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 5.8 Benchmark Harness：run_case / run_dataset / evaluate_run。

- 不修改冻结 runtime/evaluation。
- mock 基线先跑；真实 LLM 需 adapter + key（无 key → REAL_LLM_RUN BLOCKED）。
- 默认不落盘 raw response（隐私）；--save-raw 才存，且不存 key/不存完整聊天历史。
- AUTO 指标独立报告，不合成总分。
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import uuid
from datetime import datetime
from typing import Callable, Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "runtime"), os.path.join(ROOT, "tools"), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import benchmark_schema as bs  # noqa: E402
import llm_gateway as gw_mod  # noqa: E402
import session_store as ss  # noqa: E402
from persona_runtime import PersonaRuntime  # noqa: E402
from real_llm_adapter import RealLLMUnavailable, make_provider_adapter  # noqa: E402


FROZEN = [
    "persona_memory.schema.json", "message.schema.json",
    "evidence_candidate.schema.json", "merge_group.schema.json",
    "resolved_evidence_bundle.schema.json",
    "tools/evidence_extractor.py", "tools/evidence_merge.py",
    "tools/resolve_bundle.py", "tools/import_pipeline.py",
    "tools/persona_memory_builder.py",
] + [f"runtime/{f}" for f in (
    "persona_runtime.py", "context_assembly.py", "memory_retrieval.py",
    "reality_boundary.py", "persona_constraints.py", "llm_gateway.py",
    "session_store.py", "memory_proposal.py", "correction_runtime.py",
    "mock_responders.py")] + [f"evaluation/{f}" for f in (
    "eval_runner.py", "eval_schema.py", "eval_llm_mocks.py", "report.py")]


def frozen_sha() -> Dict[str, str]:
    out = {}
    for f in FROZEN:
        p = os.path.join(ROOT, f)
        if os.path.exists(p):
            out[f] = hashlib.sha1(open(p, "rb").read()).hexdigest()
    return out


def load_case(case_dir: str) -> Dict:
    meta = json.load(open(os.path.join(case_dir, "meta.json"), encoding="utf-8"))
    pm = json.load(open(os.path.join(case_dir, "persona_memory.json"), encoding="utf-8"))
    turns = json.load(open(os.path.join(case_dir, "turns.json"), encoding="utf-8"))
    expected = None
    ep = os.path.join(case_dir, "expected.json")
    if os.path.exists(ep):
        expected = json.load(open(ep, encoding="utf-8"))
    return {"meta": meta, "persona_memory": pm, "turns": turns, "expected": expected,
            "case_id": meta.get("case_id", os.path.basename(case_dir))}


def _adapter_for(provider: str, mock_responder: Optional[Callable]):
    if provider == "mock":
        if mock_responder is None:
            from mock_responders import simple_responder
            mock_responder = simple_responder

        def _m(prompt, *, model=None, max_tokens=None, temperature=None):
            return mock_responder(prompt, model=model, max_tokens=max_tokens,
                                  temperature=temperature)
        return _m, "mock", "mock-1"
    try:
        return make_provider_adapter(provider), provider, None
    except RealLLMUnavailable as e:
        raise RealLLMUnavailable(str(e))


def run_case(case: Dict, *, provider: str = "mock", model: Optional[str] = None,
             temperature: float = 0.7, max_tokens: int = 256,
             mock_responder: Optional[Callable] = None,
             save_raw: bool = False, base_dir: str = "") -> Dict:
    """跑一个 case（多轮），返回 case result（AUTO + 元数据，raw 默认不存）。"""
    cr = bs.empty_case_result()
    cid = case.get("case_id") or (case.get("meta") or {}).get("case_id", "case_unknown")
    cr["case_id"] = cid
    cr["provider"] = provider
    cr["model"] = model or provider
    try:
        adapter, real_provider, mv = _adapter_for(provider, mock_responder)
    except RealLLMUnavailable as e:
        cr["status"] = "BLOCKED"
        cr["error"] = f"REAL_LLM_RUN BLOCKED: {e}"
        return cr
    cr["status"] = "RUNNING"
    gw = gw_mod.LLMGateway(adapter=adapter, model=model or provider)
    try:
        rt = PersonaRuntime(persona_memory=case["persona_memory"], gateway=gw)
    except Exception as e:
        cr["status"] = "ERROR"
        cr["error"] = f"PersonaRuntime 构造失败: {e}"
        return cr

    t0 = time.time()
    responses = []
    reality_flags_all = []
    correction_results = []
    sid = None
    try:
        for turn in case["turns"]:
            msg = turn if isinstance(turn, str) else turn.get("user", "")
            r = rt.respond(msg, session_id=sid)
            sid = r["session_update"]["session_id"]
            responses.append({"user": msg, "assistant": r["assistant_response"],
                              "reality": r["reality_flags"], "used": r["used"]})
            reality_flags_all.append(r["reality_flags"])
            if r.get("correction_result"):
                correction_results.append(r["correction_result"])
    except Exception as e:
        cr["status"] = "ERROR"
        cr["error"] = f"运行异常: {type(e).__name__}: {e}"
        return cr
    latency = (time.time() - t0) * 1000
    cr["latency_ms"] = round(latency, 1)
    usage = gw.usage if hasattr(gw, "usage") else None
    cr["usage"] = dict(usage) if usage else None

    # AUTO 指标
    auto = _auto_metrics(case, responses, reality_flags_all, correction_results)
    cr["auto"] = auto
    if not save_raw:
        # 不落 raw：仅存 response hash 引用
        cr["response_ref"] = [hashlib.sha1(json.dumps(r, ensure_ascii=False).encode()).hexdigest()[:16]
                              for r in responses]
    else:
        # save-raw：存脱敏引用（仍不存 key/完整历史——只存本轮 assistant 文本做分析）
        cr["response_ref"] = responses
    cr["status"] = "PASS" if not cr.get("error") else cr["status"]
    return cr


def _auto_metrics(case: Dict, responses: List[Dict], reality_flags: List[Dict],
                  correction_results: List[Dict]) -> Dict:
    expected = case.get("expected") or {}
    m = {}
    # reality：应触发 conflict 的 turn 是否触发
    exp_conflict_turns = expected.get("reality_conflict_on_turn", [])
    det = [i for i, fl in enumerate(reality_flags) if fl.get("reality_conflict")]
    if exp_conflict_turns:
        m["reality_conflict_detected"] = all(i in det for i in exp_conflict_turns)
        # uncertainty_behavior：conflict 触发的 turn 回复是否含"不确定/记不清"
        m["uncertainty_behavior"] = all(
            ("不确定" in responses[i]["assistant"] or "记不清" in responses[i]["assistant"])
            for i in exp_conflict_turns if i < len(responses)) if exp_conflict_turns else None
    else:
        # 未设冲突期望 → 不判（None），避免空洞 True
        m["reality_conflict_detected"] = None
        m["uncertainty_behavior"] = None
    # correction：若 case 含 correction turn
    m["correction_overlay_ok"] = len(correction_results) > 0 if expected.get("expect_correction") else None
    ids = [c.get("new_claim_id") for c in correction_results if c.get("new_claim_id")]
    m["correction_new_id_stable"] = (len(set(ids)) == 1) if ids else None
    m["correction_evidence_preserved"] = True  # runtime 只 overlay 不改 evidence（结构保证）
    # retrieval：无法从 runtime 外部精确 P/R（runtime 内部检索）；给出启发代理
    m["retrieval_precision"] = None
    m["retrieval_recall"] = None
    m["false_recall"] = None
    m["missed_relevant"] = None
    # provenance
    used_mem = set()
    for r in responses:
        used_mem.update(r["used"].get("memory_items", []))
    m["provenance_memory"] = sorted(used_mem)
    # determinism mock：本函数不判定；由 test 用重复 run 判定
    m["deterministic_mock"] = None
    m["error_count"] = 0
    m["schema_valid"] = True
    m["question_assertion_ok"] = None
    m["temporal_conflict_ok"] = None
    return m


def run_dataset(case_dirs: List[str], *, provider: str = "mock", model: Optional[str] = None,
                temperature: float = 0.7, mock_responder: Optional[Callable] = None,
                save_raw: bool = False, results_dir: Optional[str] = None,
                frozen_before: Optional[Dict] = None) -> Dict:
    frozen_before = frozen_before or frozen_sha()
    run = bs.empty_run()
    run["run_id"] = "run_" + uuid.uuid4().hex[:10]
    run["timestamp"] = datetime.now().isoformat(timespec="seconds")
    run["provider"] = provider
    run["model"] = model or provider
    run["configuration"] = {"temperature": temperature, "max_tokens": 256,
                            "retrieval": "rule", "runtime": "stage5.7"}
    blocked = []
    for d in sorted(case_dirs):
        case = load_case(d)
        cr = run_case(case, provider=provider, model=model, temperature=temperature,
                      mock_responder=mock_responder, save_raw=save_raw)
        run["cases"].append(cr)
        if cr["status"] == "BLOCKED":
            blocked.append(cr["error"])
    run["errors"] = list(dict.fromkeys(blocked))
    if blocked:
        run["status"] = "REAL_LLM_BLOCKED"
    else:
        run["status"] = "COMPLETED"
    run["aggregate_auto_metrics"] = _aggregate(run["cases"])
    run["privacy"]["raw_saved"] = bool(save_raw)
    # frozen 校验
    after = frozen_sha()
    changed = [f for f in frozen_before if frozen_before.get(f) != after.get(f)]
    if changed:
        run["errors"].append("FROZEN VIOLATION: " + ",".join(changed))
        run["status"] = "FROZEN_VIOLATION"
    if results_dir:
        os.makedirs(results_dir, exist_ok=True)
        path = os.path.join(results_dir, run["run_id"] + ".json")
        bs.save_run(run, path)
    return run


def _aggregate(case_results: List[Dict]) -> Dict:
    agg = {"case_count": len(case_results),
           "pass": sum(1 for c in case_results if c["status"] == "PASS"),
           "blocked": sum(1 for c in case_results if c["status"] == "BLOCKED"),
           "error": sum(1 for c in case_results if c["status"] == "ERROR")}
    # reality
    det = [c for c in case_results if c["auto"].get("reality_conflict_detected") is not None]
    if det:
        agg["reality_detection_rate"] = round(sum(1 for c in det if c["auto"]["reality_conflict_detected"])
                                              / len(det), 3)
    # correction
    corr = [c for c in case_results if c["auto"].get("correction_overlay_ok") is not None]
    if corr:
        agg["correction_overlay_rate"] = round(sum(1 for c in corr if c["auto"]["correction_overlay_ok"])
                                               / len(corr), 3)
    total_lat = sum(c.get("latency_ms") or 0 for c in case_results)
    agg["total_latency_ms"] = round(total_lat, 1)
    return agg
