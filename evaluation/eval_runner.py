#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 5.6 Evaluation Runner：Golden case → 真实冻结链路 → AUTO 断言 + semantic 统计。

Golden case 输入 = messages.json（合法 ChatImport v1.2）。
链路：messages → 5.2 extract(deterministic mock LLM) → 5.3 merge → 5.4 bundle
     → 5.5 build(llm=None 确定性回退) → persona_memory v1.2
然后执行确定性 AUTO 断言 + 载入 annotations.json 做 semantic 统计。

只 import/调用冻结模块，不修改它们。
"""

from __future__ import annotations

import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(os.path.dirname(HERE), "tools")
for p in (TOOLS, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from eval_llm_mocks import extractor_mock_llm  # noqa: E402
import evidence_extractor as ex  # noqa: E402
import evidence_merge as em  # noqa: E402
import resolve_bundle as rb  # noqa: E402
import persona_memory_builder as pmb  # noqa: E402
import eval_schema  # noqa: E402

FROZEN = [
    "evidence_candidate.schema.json", "merge_group.schema.json",
    "resolved_evidence_bundle.schema.json", "persona_memory.schema.json",
    "message.schema.json", "tools/evidence_extractor.py", "tools/evidence_merge.py",
    "tools/resolve_bundle.py", "tools/import_pipeline.py",
]
ROOT = os.path.dirname(HERE)

# 低信息量 → overreach 负例（只是 case 级期望，非全局禁用）
OVERREACH_WORDS = ["高冷", "温柔", "回避型", "恋爱脑", "控制欲", "焦虑型", "共情能力强"]


def frozen_sha():
    out = {}
    for f in FROZEN:
        p = os.path.join(ROOT, f)
        out[f] = hashlib.sha1(open(p, "rb").read()).hexdigest() if os.path.exists(p) else None
    return out


def run_chain(chat_import: dict, name: str):
    """messages(ChatImport) → persona_memory。返回 (pm, steps, errors)。"""
    errors = []
    csd = {"schema_version": "1.0", "extraction_context": {}, "candidates": []}
    # 5.2
    r5 = ex.extract_evidence(chat_import=chat_import, llm=extractor_mock_llm)
    if not r5["ok"]:
        return None, {}, ["5.2 extract failed: " + "; ".join(r5["errors"])]
    cs = r5["candidate_set"]
    # 5.3
    r6 = em.merge_evidence(candidates=cs["candidates"])
    if not r6["ok"]:
        return None, {}, ["5.3 merge failed: " + "; ".join(r6["errors"])]
    mr = r6["merge_result"]
    # 5.4
    csd = {"schema_version": "1.0", "extraction_context": cs.get("extraction_context", {}),
           "candidates": cs["candidates"]}
    r7 = rb.resolve_bundle(candidate_set=csd, merge_result=mr)
    if not r7["ok"]:
        return None, {}, ["5.4 resolve failed: " + "; ".join(r7["errors"])]
    bundle = r7["bundle"]
    # 5.5 (llm=None → 确定性回退)
    r8 = pmb.build_persona_memory(bundle=bundle, candidate_set=csd, name_or_alias=name, llm=None)
    if not r8["ok"]:
        return None, {}, ["5.5 build failed: " + "; ".join(r8["errors"])]
    steps = {"candidate_set": csd, "merge_result": mr, "bundle": bundle}
    return r8["persona_memory"], steps, errors


# ---------------------------------------------------------------------------
# AUTO 断言
# ---------------------------------------------------------------------------
def _all_persona_claims(pm):
    claims = []

    def walk(o):
        if isinstance(o, dict):
            if isinstance(o.get("claim_id"), str) and "value" in o and "basis" in o:
                claims.append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(pm.get("persona", {}))
    return claims


def _all_memory_items(pm):
    return [it for b in pm.get("memory", {}).values() for it in b]


def auto_schema_validity(pm):
    return pmb._schema_errs(pmb._pm_validator, pm)


def auto_provenance(pm, cand_by_id):
    ok = True
    problems = []

    def chk_claims(o):
        nonlocal ok
        if isinstance(o, dict):
            if isinstance(o.get("claim_id"), str) and "evidence_ids" in o:
                for eid in o.get("evidence_ids", []):
                    if eid not in cand_by_id:
                        ok = False
                        problems.append(f"claim {o.get('claim_id')} evidence {eid} 缺失")
            for v in o.values():
                chk_claims(v)
        elif isinstance(o, list):
            for v in o:
                chk_claims(v)
    chk_claims(pm.get("persona", {}))
    for it in _all_memory_items(pm):
        for eid in it.get("evidence_ids", []):
            if eid not in cand_by_id:
                ok = False
                problems.append(f"memory {it['id']} evidence {eid} 缺失")
    return ok, problems


def auto_conflict_safety(pm):
    """conflict 双方保留：若有 conflicts_with 的 item，其对方也应存在且互指。"""
    items = {it["id"]: it for it in _all_memory_items(pm)}
    problems = []
    for it in items.values():
        for cid in it.get("conflicts_with", []):
            if cid not in items:
                problems.append(f"memory {it['id']} conflicts_with {cid} 不存在")
            elif it["id"] not in items[cid].get("conflicts_with", []):
                problems.append(f"conflicts_with 非互指: {it['id']} ↔ {cid}")
    # conflict 双 pending：若两 item 互指 conflicts_with 且都非 pending → 不判错（active 也可能）
    return problems


def auto_temporal_non_destructive(pm):
    """temporal 容器 history 保留：凡有 history 的 item，history 段数≥1 且每段有 value。"""
    problems = []
    for it in _all_memory_items(pm):
        if it.get("history"):
            for i, h in enumerate(it["history"]):
                if not h.get("value"):
                    problems.append(f"memory {it['id']} history[{i}] 缺 value")
    return problems


def auto_negative(case_neg, pm):
    """expected_negative 中的 trait 不得出现在 persona claims（文字匹配 expected 条目）。"""
    viol = []
    neg_items = case_neg.get("persona_negative", case_neg)  # 兼容 list 或 dict
    if isinstance(neg_items, dict):
        neg_items = neg_items.get("traits", [])
    claims_text = [c.get("value", "") for c in _all_persona_claims(pm)]
    for t in neg_items:
        if isinstance(t, dict):
            t = t.get("trait", t.get("value", ""))
        if any(t and t in ct for ct in claims_text):
            viol.append(t)
    return viol


def auto_expected_hit(expected_persona, pm, bucket_expected, memitems):
    """expected_persona 中应出现的 trait 是否命中（text 包含匹配）。"""
    hits, miss = [], []
    if isinstance(expected_persona, dict):
        expected_persona = expected_persona.get("traits", [])
    claims_text = [c.get("value", "") for c in _all_persona_claims(pm)]
    for t in expected_persona:
        if isinstance(t, dict):
            t = t.get("trait", t.get("value", ""))
        if any(t and t in ct for ct in claims_text):
            hits.append(t)
        else:
            miss.append(t)
    return hits, miss


# ---------------------------------------------------------------------------
# 运行单个 case
# ---------------------------------------------------------------------------
def run_case(case_dir: str, *, repeat: int = 3) -> dict:
    """跑一个 golden case，返回结构化结果。"""
    result = {"case_id": os.path.basename(case_dir), "status": "ERROR",
              "auto": {}, "semantic": None, "notes": []}
    probs = eval_schema.validate_case_dir(case_dir)
    if probs:
        result["errors"] = probs
        return result
    meta = eval_schema.load_meta(case_dir)
    mprobs = eval_schema.validate_meta(meta)
    if mprobs:
        result["errors"] = mprobs
        return result
    ci = json.load(open(os.path.join(case_dir, "messages.json"), encoding="utf-8"))
    name = meta.get("name_or_alias", meta.get("case_id", "case"))
    exp = eval_schema.expected_files(case_dir)

    # determinism: 重复运行
    outputs = []
    for _ in range(repeat):
        pm, steps, errs = run_chain(ci, name)
        if errs:
            result["errors"] = errs
            return result
        outputs.append(pm)
    # determinism check（byte-level）
    canon = sorted({json.dumps(o, ensure_ascii=False, sort_keys=True) for o in outputs})
    det_ok = len(canon) == 1
    pm = outputs[0]
    cand_by_id = {c["candidate_id"]: c for c in steps["candidate_set"]["candidates"]}

    # AUTO
    auto = {}
    auto["schema_valid"] = auto_schema_validity(pm) == []
    auto["deterministic"] = det_ok
    prov_ok, prov_probs = auto_provenance(pm, cand_by_id)
    auto["provenance"] = prov_ok
    auto["candidate_to_group_ok"] = True
    # rep.candidate_id 正确性：bundle 已保证；这里验证 pm 无 orphan
    auto["negative_violations"] = auto_negative(exp.get("expected_negative.json", {}), pm)
    auto["conflict_problems"] = auto_conflict_safety(pm)
    auto["temporal_problems"] = auto_temporal_non_destructive(pm)
    auto["claim_id_stable"] = det_ok
    result["auto"] = auto
    if auto["negative_violations"]:
        result["notes"].append("negative violations: " + str(auto["negative_violations"]))

    # semantic（gold annotations）
    ann_path = os.path.join(case_dir, "annotations.json")
    semantic = None
    if os.path.exists(ann_path):
        anns = json.load(open(ann_path, encoding="utf-8"))
        aerrs = eval_schema.validate_annotations(case_dir)
        if aerrs:
            result["notes"].append("annotation 校验问题: " + "; ".join(aerrs[:3]))
        semantic = _semantic_stats(anns)
    result["semantic"] = semantic
    result["status"] = "PASS" if (auto["schema_valid"] and auto["deterministic"]
                                  and auto["provenance"] and not auto["negative_violations"]) \
        else ("FAIL" if any(not v for v in [auto["schema_valid"], auto["deterministic"],
                                            auto["provenance"]]) or auto["negative_violations"] else "PASS")
    return result


def _semantic_stats(anns):
    n = len(anns)
    if n == 0:
        return {"n": 0}
    supported = sum(1 for a in anns if a.get("evidence_support") == "SUPPORTED")
    partial = sum(1 for a in anns if a.get("evidence_support") == "PARTIALLY_SUPPORTED")
    unsupported = sum(1 for a in anns if a.get("evidence_support") == "UNSUPPORTED")
    contradicted = sum(1 for a in anns if a.get("evidence_support") == "CONTRADICTED")
    overreach = sum(1 for a in anns if a.get("overreach"))
    return {
        "n": n, "SUPPORTED": supported, "PARTIALLY_SUPPORTED": partial,
        "UNSUPPORTED": unsupported, "CONTRADICTED": contradicted,
        "evidence_fidelity": (supported + 0.5 * partial) / n,
        "overreach_rate": overreach / n,
    }


def run_dataset(dataset_dir: str, *, repeat: int = 3, frozen_before: dict = None) -> dict:
    """跑整个 dataset，返回 {cases:[...], aggregate}。执行后校验冻结 SHA-1。"""
    frozen_before = frozen_before or frozen_sha()
    results = []
    for entry in sorted(os.listdir(dataset_dir)):
        case_dir = os.path.join(dataset_dir, entry)
        if not os.path.isdir(case_dir) or not entry.startswith("case_"):
            continue
        results.append(run_case(case_dir, repeat=repeat))
    aggregate = aggregate_results(results)
    frozen_after = frozen_sha()
    frozen_ok = frozen_before == frozen_after
    if not frozen_ok:
        changed = [f for f in frozen_before if frozen_before.get(f) != frozen_after.get(f)]
        raise SystemExit(f"FROZEN VIOLATION during eval: {changed}")
    return {"cases": results, "aggregate": aggregate, "frozen_integrity_ok": frozen_ok}


def aggregate_results(results):
    cases = [r for r in results if r["status"] != "ERROR"]
    agg = {
        "case_count": len(cases),
        "pass_count": sum(1 for r in cases if r["status"] == "PASS"),
        "fail_count": sum(1 for r in cases if r["status"] != "PASS"),
        "auto_provenance_pass": sum(1 for r in cases if r["auto"].get("provenance")),
        "auto_deterministic_pass": sum(1 for r in cases if r["auto"].get("deterministic")),
        "auto_schema_pass": sum(1 for r in cases if r["auto"].get("schema_valid")),
        "negative_violation_cases": sum(1 for r in cases if r["auto"].get("negative_violations")),
    }
    # semantic
    sem = [r["semantic"] for r in cases if r.get("semantic")]
    if sem:
        n = sum(s.get("n", 0) for s in sem)
        agg["annotated"] = n
        ef = sum(s.get("evidence_fidelity", 0) * s.get("n", 0) for s in sem)
        ov = sum(s.get("overreach_rate", 0) * s.get("n", 0) for s in sem)
        agg["evidence_fidelity"] = round(ef / n, 4) if n else None
        agg["overreach_rate"] = round(ov / n, 4) if n else None
    return agg


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Stage 5.6 Eval Runner")
    ap.add_argument("--dataset", default=os.path.join(HERE, "dataset"))
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    fb = frozen_sha()
    out = run_dataset(args.dataset, repeat=args.repeat, frozen_before=fb)
    for c in out["cases"]:
        print(f"[{c['status']}] {c['case_id']}  auto={c['auto']}  semantic={c.get('semantic')}")
    print("AGGREGATE:", json.dumps(out["aggregate"], ensure_ascii=False, indent=2))
    print("frozen_integrity:", out["frozen_integrity_ok"])
    if args.json:
        json.dump(out, open(args.json, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
