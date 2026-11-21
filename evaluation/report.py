#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 5.6 Evaluation Report：聚合 + Before/After 对比。

不制造单一"综合分数"——输出多个独立指标；before/after 逐指标对比。
输入 = 两次 run_dataset 的返回 dict（或两个保存的 run JSON）。
"""

from __future__ import annotations

import json
import os
import sys


def _load_run(path_or_dict):
    if isinstance(path_or_dict, dict):
        return path_or_dict
    with open(path_or_dict, encoding="utf-8") as f:
        return json.load(f)


def report_run(run) -> dict:
    agg = run.get("aggregate", {})
    return {
        "case_count": agg.get("case_count", 0),
        "pass": agg.get("pass_count", 0),
        "fail": agg.get("fail_count", 0),
        "auto_provenance_pass": agg.get("auto_provenance_pass", 0),
        "auto_deterministic_pass": agg.get("auto_deterministic_pass", 0),
        "auto_schema_pass": agg.get("auto_schema_pass", 0),
        "negative_violation_cases": agg.get("negative_violation_cases", 0),
        "annotated": agg.get("annotated", 0),
        "evidence_fidelity": agg.get("evidence_fidelity"),
        "overreach_rate": agg.get("overreach_rate"),
    }


def compare(base_run, cand_run) -> dict:
    b = report_run(_load_run(base_run))
    c = report_run(_load_run(cand_run))
    out = {"baseline": b, "candidate": c, "deltas": {}}
    keys = ["pass", "fail", "auto_provenance_pass", "auto_deterministic_pass",
            "auto_schema_pass", "negative_violation_cases", "evidence_fidelity",
            "overreach_rate"]
    for k in keys:
        bv, cv = b.get(k), c.get(k)
        if isinstance(bv, (int, float)) and isinstance(cv, (int, float)):
            out["deltas"][k] = round(cv - bv, 4)
        else:
            out["deltas"][k] = None
    return out


def format_compare(comp: dict) -> str:
    lines = ["=== Before / After ===", f"{'metric':<28}{'before':>10}{'after':>10}{'delta':>10}"]
    b, c, d = comp["baseline"], comp["candidate"], comp["deltas"]
    for k in ["pass", "fail", "auto_provenance_pass", "auto_deterministic_pass",
              "auto_schema_pass", "negative_violation_cases"]:
        lines.append(f"{k:<28}{str(b.get(k)):>10}{str(c.get(k)):>10}{str(d.get(k)):>10}")
    for k in ["evidence_fidelity", "overreach_rate"]:
        bb = f"{b.get(k):.3f}" if isinstance(b.get(k), float) else "n/a"
        cc = f"{c.get(k):.3f}" if isinstance(c.get(k), float) else "n/a"
        dd = f"{d.get(k):+.3f}" if isinstance(d.get(k), float) else ""
        lines.append(f"{k:<28}{bb:>10}{cc:>10}{dd:>10}")
    return "\n".join(lines)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Stage 5.6 Report (aggregate / before-after)")
    ap.add_argument("--base", required=True, help="baseline run JSON")
    ap.add_argument("--candidate", required=True, help="candidate run JSON")
    args = ap.parse_args(argv)
    comp = compare(args.base, args.candidate)
    print(format_compare(comp))
    return 0


if __name__ == "__main__":
    sys.exit(main())
