#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""编造探针（v0.3.0 第 2 项）：测"没记录时会不会编共同经历"。

走产品真实上下文：`persona_loader` → `assess_support` → `context_assembly` → 同一个
system/user prompt 交给本地模型。区别只在温度固定 0.0（评测复现优先）。

用法：
  EX_MODEL=yuwen-4b-q4 python benchmark/fabrication_probe/run_probe.py \
      --model yuwen-4b-q4 --runs 3 --out benchmark/fabrication_probe/baseline_q4.json

不判分：只落原始回复 + 上下文边界状态，判定由人工复核后写入 baseline_summary.md。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for _p in (ROOT, os.path.join(ROOT, "runtime"), os.path.join(ROOT, "tools"),
           os.path.join(ROOT, "benchmark"), os.path.join(ROOT, "evaluation")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import eval_runner as er  # noqa: E402
import reality_boundary as rb  # noqa: E402
import memory_retrieval as mr  # noqa: E402
import context_assembly as ca  # noqa: E402
import llm_gateway as lg  # noqa: E402
import real_llm_adapter as rla  # noqa: E402


def _sample_path() -> str:
    p = os.path.join(ROOT, "dist_pkg", "dist", "ex-ai-pilot", "sample_messages.json")
    if os.path.exists(p):
        return p
    return os.path.join(ROOT, "evaluation", "dataset", "case_001", "messages.json")


def build_pm():
    chat = json.load(open(_sample_path(), encoding="utf-8"))
    pm, _, errs = er.run_chain(chat, "小明")
    if errs:
        raise SystemExit(f"建人格失败: {errs}")
    return pm


def run(model: str, runs: int, out_path: str, temperature: float = 0.0, seed: int = 42,
        with_holdout: bool = False, only=None):
    os.environ["YUWEN_BACKEND"] = "local"
    os.environ["OPENAI_BASE_URL"] = os.environ.get("OPENAI_BASE_URL", "http://localhost:11434/v1")
    os.environ["EX_MODEL"] = model

    pm = build_pm()
    qs = json.load(open(os.path.join(HERE, "questions.json"), encoding="utf-8"))
    if with_holdout:
        ho = json.load(open(os.path.join(HERE, "holdout.json"), encoding="utf-8"))
        qs = dict(qs)
        qs["holdout"] = ho["holdout"]
    p2 = os.path.join(HERE, "holdout2.json")
    if os.path.exists(p2):
        h2 = json.load(open(p2, encoding="utf-8"))
        qs = dict(qs)
        qs["holdout2"] = h2.get("holdout2", [])
        qs["b2_group"] = h2.get("b2_group", [])

    def adapter(prompt, *, model=None, max_tokens=512, temperature=0.7):
        r = rla.local_chat(prompt, model=model or os.environ["EX_MODEL"],
                           max_tokens=max_tokens, temperature=temperature, seed=seed)
        return r["text"]

    if only:
        qs = {k: v for k, v in qs.items() if k in only}
        print("只跑组:", list(qs))

    gw = lg.LLMGateway(adapter=adapter, model=model)

    rows = []
    for group in ("a_group", "b_group", "c_group", "holdout", "holdout2", "b2_group"):
        if group not in qs:
            continue
        for item in qs[group]:
            q = item["q"]
            flags = rb.check_reality(pm, q)
            retrieved = mr.retrieve(pm, {}, q, k=5, now=None)
            support = rb.assess_support(pm, q, retrieved_items=retrieved.get("items", []), flags=flags)
            flags.update(support)
            ctx = ca.assemble(pm, "小明", q, retrieved=retrieved, session_recent=[],
                              reality_flags=flags)
            msgs = [lg.ChatMessage("system", ctx["system_text"]),
                    lg.ChatMessage("user", ctx["user_text"])]
            for i in range(runs):
                t0 = time.time()
                try:
                    reply = gw.chat(msgs, model=model, max_tokens=256, temperature=temperature)
                    err = None
                except Exception as e:  # noqa: BLE001
                    reply, err = "", f"{type(e).__name__}: {e}"
                dt = time.time() - t0
                rows.append({
                    "group": group, "id": item["id"], "q": q, "run": i + 1,
                    "reply": reply, "error": err, "seconds": round(dt, 2),
                    "boundary_state": flags.get("boundary_state"),
                    "boundary_active": flags.get("boundary_active"),
                    "retrieved": [x["memory"]["content"] for x in retrieved.get("items", [])],
                })
                print(f"[{item['id']}#{i+1}] {dt:.1f}s boundary={flags.get('boundary_state')} "
                      f"-> {(reply or err or '')[:60]!r}")

    payload = {"model": model, "runs_per_question": runs, "temperature": temperature,
               "seed": seed, "with_holdout": with_holdout,
               "sample": os.path.basename(_sample_path()), "rows": rows}
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    json.dump(payload, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\nsaved -> {out_path}  ({len(rows)} 条)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", required=True)
    ap.add_argument("--holdout", action="store_true")
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    only = [x.strip() for x in a.only.split(",") if x.strip()] or None
    run(a.model, a.runs, a.out, a.temperature, a.seed, a.holdout, only)


if __name__ == "__main__":
    main()
