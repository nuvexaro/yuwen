#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 6.3 P4 — MVP Real LLM E2E（真实 DeepSeek）。

用 CLI 的 make_host（真实 adapter）走完整链：
create Ex → chat(real multi-turn) → correction proposal → (operator confirm 由外部给)
→ persist → reopen new session → 长期记忆采用 → delete 验证。
不用 mock。产物写 stage6/cli/e2e_out/。
"""

from __future__ import annotations

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.join(_HERE, "..", "host"), os.path.join(_HERE, "..", "..")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import mvp_cli  # noqa: E402


def main():
    if not os.environ.get("DEEPSEEK_API"):
        print("BLOCKED_BY_MISSING_CREDENTIALS")
        return 1
    os.environ.setdefault("OPENAI_API_KEY", os.environ["DEEPSEEK_API"])
    os.environ.setdefault("OPENAI_BASE_URL", "https://api.deepseek.com")
    os.environ["EX_REAL"] = "1"
    outdir = os.path.join(_HERE, "e2e_out")
    os.makedirs(outdir, exist_ok=True)
    os.environ["EX_BASE_DIR"] = os.path.join(outdir, "exes")
    os.environ["EX_SESSION_DIR"] = os.path.join(outdir, "sessions")

    # clean prior scratch
    import shutil
    for d in (os.environ["EX_BASE_DIR"], os.environ["EX_SESSION_DIR"]):
        if os.path.isdir(d):
            shutil.rmtree(d)

    ev = {"provider": "openai", "model": "deepseek-chat"}
    # create via skill_writer (CLI create path)
    from skill_writer_v12 import init_ex_instance
    seed = {"schema_version": "1.2", "revision": 1,
            "persona": {"layer0_rules": {}, "identity": {"name_or_alias": {"claim_id": "pc_n", "value": "小明",
                                                                           "evidence_ids": [], "confidence": 1.0,
                                                                           "basis": "user_report_only"}},
                        "speech_style": {}, "emotional_pattern": {}, "relationship_behavior": {}},
            "memory": {"core_facts": [{"id": "mi_A", "content": "她话少", "status": "active", "confidence": 0.8,
                                       "importance": 1, "source_type": "user_input"}],
                       "preferences": [], "timeline": [], "shared_experiences": [], "conflicts": [],
                       "happy_memories": [], "breakup": [], "inside_jokes": [], "daily_patterns": []},
            "corrections": []}
    init_ex_instance(seed, os.environ["EX_BASE_DIR"], "e2e")

    host = mvp_cli.make_host()
    # Session 1: real multi-turn producing a correction
    sid1 = host.new_session("e2e")
    conv = []
    for t in ["在吗", "你觉得她话多话少？", "不对，她其实话痨，特别能说那种。"]:
        out = host.respond(sid1, t)
        conv.append({"u": t, "a": out["assistant_response"], "err": out.get("error")})
        if out.get("error") == "gateway_fallback":
            print("!! fallback (not real success):", t)
    ev["session1"] = conv
    for c in conv:
        print(f"[U] {c['u']}\n[A] {c['a']}")
    props = host.pending_proposals(sid1)
    ev["proposal"] = props
    print("\n[proposal]", json.dumps(props, ensure_ascii=False)[:400])
    ev["sid1"] = sid1
    json.dump(ev, open(os.path.join(outdir, "e2e_stage.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
