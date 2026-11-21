#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 6.3 P4 — MVP Real E2E part2：confirm → persist → reopen → adopt → delete check."""

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
    os.environ.setdefault("OPENAI_API_KEY", os.environ["DEEPSEEK_API"])
    os.environ.setdefault("OPENAI_BASE_URL", "https://api.deepseek.com")
    os.environ["EX_REAL"] = "1"
    outdir = os.path.join(_HERE, "e2e_out")
    os.environ["EX_BASE_DIR"] = os.path.join(outdir, "exes")
    os.environ["EX_SESSION_DIR"] = os.path.join(outdir, "sessions")
    stage = json.load(open(os.path.join(outdir, "e2e_stage.json"), encoding="utf-8"))
    sid1 = stage["sid1"]; pid = stage["proposal"][0]["proposal_id"]

    host = mvp_cli.make_host()
    host.attach_session("e2e", sid1)
    res = host.confirm_proposal(sid1, pid)
    print("[persist]", json.dumps(res, ensure_ascii=False))
    pm = json.load(open(os.path.join(os.environ["EX_BASE_DIR"], "e2e", "persona_memory.json"), encoding="utf-8"))
    print("[canonical]", {"revision": pm.get("revision"),
                          "corrections": [(c["id"], c["status"]) for c in pm["corrections"]],
                          "mi_A": [(m["id"], m["status"]) for m in pm["memory"]["core_facts"]]})

    # reopen new session → real adopt (content-anchored per referent Known Limit)
    sid2 = host.new_session("e2e")
    adopt = []
    for q in ["还记得你之前改口说她话痨吗？", "她话多吗？"]:
        out = host.respond(sid2, q)
        adopt.append({"q": q, "a": out["assistant_response"], "err": out.get("error")})
        print(f"\n[reopen U] {q}\n[reopen A] {out['assistant_response']}")

    # delete verification
    class A:
        ex = "e2e"
    rc = mvp_cli.cmd_delete(A())
    deleted = not os.path.exists(os.path.join(os.environ["EX_BASE_DIR"], "e2e")) \
        and not os.path.exists(os.path.join(os.environ["EX_SESSION_DIR"], "e2e"))
    print("\n[delete] rc:", rc, "| data cleared:", deleted)

    ev = {"persist": res, "canonical": {"revision": pm.get("revision"),
          "corrections": [(c["id"], c["status"]) for c in pm["corrections"]]},
          "reopen_adopt": adopt, "delete_ok": deleted}
    json.dump(ev, open(os.path.join(outdir, "e2e_final.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
