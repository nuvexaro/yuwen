#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Frozen reopen test — Failure Observability（gateway_fallback error field）。

验证（授权 reopen scope）：
  1. Failure：adapter 连续失败 → gateway retry → GatewayError → fallback → response.error == "gateway_fallback"
  2. Success：adapter 成功 → 正常 response → 无 error == "gateway_fallback"
  3. Existing error：context_budget_exceeded 既有 error 字段行为不变
  4. No semantic change：fallback 文本不变；correction/A′/F5 行为不变（success 路径无 error）
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.dirname(HERE)
for p in (RUNTIME,):
    if p not in sys.path:
        sys.path.insert(0, p)

from llm_gateway import LLMGateway  # noqa: E402
from persona_runtime import PersonaRuntime  # noqa: E402


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


def mk(adapter, retry=1, budget=2000):
    pm = {"schema_version": "1.2", "persona": {
        "identity": {"name_or_alias": {"claim_id": "pc_n", "value": "X", "evidence_ids": [],
                                       "confidence": 1.0, "basis": "user_report_only"}},
        "layer0_rules": {}, "speech_style": {}, "emotional_pattern": {}, "relationship_behavior": {}},
        "memory": {"core_facts": [], "preferences": [], "timeline": [], "shared_experiences": [],
                   "conflicts": [], "happy_memories": [], "breakup": [], "inside_jokes": [],
                   "daily_patterns": []}, "corrections": []}
    g = LLMGateway(adapter=adapter, model="m", retry=retry)
    return PersonaRuntime(persona_memory=pm, gateway=g, context_budget=budget)


def main():
    print("=== Frozen reopen: failure observability ===")
    # 1. Failure
    r = mk(lambda p, **k: (_ for _ in ()).throw(TimeoutError("x")), retry=1).respond("hi", session_id="f1")
    C.ok("1: gateway fallback error field", r.get("error") == "gateway_fallback", str(r.get("error")))
    C.ok("1: fallback text unchanged", r["assistant_response"] == "……（先不说这个了。）",
         repr(r["assistant_response"]))
    # 2. Success
    r2 = mk(lambda p, **k: "好的").respond("hi", session_id="s1")
    C.ok("2: success has no gateway_fallback error", r2.get("error") != "gateway_fallback",
         str(r2.get("error")))
    C.ok("2: success text preserved", r2["assistant_response"] == "好的", repr(r2["assistant_response"]))
    # 3. Existing error (context_budget_exceeded) — tiny budget
    r3 = mk(lambda p, **k: "x", budget=1).respond("在干嘛", session_id="c1")
    C.ok("3: context_budget_exceeded error preserved", r3.get("error") == "context_budget_exceeded",
         str(r3.get("error")))
    # 4. No semantic change: retry happened in gateway before fallback
    calls = {"n": 0}
    def flaky(prompt, **k):
        calls["n"] += 1
        raise TimeoutError("always")
    mk(flaky, retry=2).respond("hi", session_id="f2")
    C.ok("4: gateway retry occurred (retry+1 calls) before fallback", calls["n"] == 3, f"calls={calls['n']}")

    print(f"\n通过 {C.ok_n} / 失败 {C.fail_n}")
    for f in C.fails:
        print("  -", f)
    sys.exit(0 if C.fail_n == 0 else 1)


if __name__ == "__main__":
    main()
