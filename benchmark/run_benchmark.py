#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 5.8 Benchmark CLI。

用法：
  python run_benchmark.py --provider mock [--all | --case case_xxx]
  python run_benchmark.py --provider anthropic --model claude-... --all
  python run_benchmark.py --provider openai   --model gpt-4o-mini --case case_...
  python run_benchmark.py --save-raw            # 显式允许保存 raw（默认不存）

无 API key 时真实 provider → 输出 REAL_LLM_RUN = BLOCKED_BY_MISSING_CREDENTIALS。
"""

from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import benchmark_harness as bh  # noqa: E402
from real_llm_adapter import RealLLMUnavailable  # noqa: E402


def _list_case_dirs(base: str):
    if not os.path.isdir(base):
        return []
    return [os.path.join(base, d) for d in sorted(os.listdir(base))
            if os.path.isdir(os.path.join(base, d)) and d.startswith("case_")]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Stage 5.8 Benchmark")
    ap.add_argument("--provider", default="mock", choices=["mock", "anthropic", "openai"])
    ap.add_argument("--model", default=None)
    ap.add_argument("--case", default=None, help="单 case（目录名 case_xxx）")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--save-raw", action="store_true", help="保存 raw response（默认不存；提示隐私）")
    ap.add_argument("--results-dir", default=os.path.join(HERE, "results"))
    ap.add_argument("--case-base", default=os.path.join(HERE, "runtime_cases"))
    args = ap.parse_args(argv)

    if args.save_raw:
        print("[warn] --save-raw 已开启：raw response 会写入 results（不含 API key；仍建议仅本地使用）")

    dirs = []
    if args.case:
        d = os.path.join(args.case_base, args.case)
        if os.path.isdir(d):
            dirs = [d]
        else:
            print(f"未找到 case 目录: {d}")
            return 2
    elif args.all or True:
        dirs = _list_case_dirs(args.case_base)
        if not dirs:
            print(f"runtime_cases 为空: {args.case_base}")
            return 2

    try:
        run = bh.run_dataset(dirs, provider=args.provider, model=args.model,
                             save_raw=args.save_raw, results_dir=args.results_dir)
    except RealLLMUnavailable as e:
        print(f"REAL_LLM_RUN = BLOCKED_BY_MISSING_CREDENTIALS: {e}")
        print("MOCK_RUN 仍可用（--provider mock）。")
        return 0

    print(f"run_id={run['run_id']} status={run['status']}")
    for c in run["cases"]:
        print(f"  [{c['status']}] {c['case_id']}  lat={c.get('latency_ms')}ms  "
              f"auto={ {k: v for k, v in c['auto'].items() if v is not None} }")
    print("AGG:", run["aggregate_auto_metrics"])
    if run["errors"]:
        print("ERRORS:", run["errors"])
    print(f"privacy raw_saved={run['privacy']['raw_saved']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
