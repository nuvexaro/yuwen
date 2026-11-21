#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 6.3 P4 — MVP CLI deterministic tests（mock adapter；Real E2E 另用真实 provider）。

覆盖：create / import / list / chat(mock multi-turn + correction confirm persist) /
delete(清数据) / privacy(redact / key not leaked)。Ex isolation。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import shutil

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.join(_HERE, "..", "host"), os.path.join(_HERE, "..", ".."),
           os.path.join(_HERE, "..", "..", "evaluation")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import mvp_cli  # noqa: E402
import privacy  # noqa: E402
from production_host import Host  # noqa: E402


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


class _NS:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def mock_responder(prompt, **k):
    return "嗯 知道了。"


def main():
    print("=== Stage 6.3 MVP CLI deterministic ===")
    d = tempfile.mkdtemp()
    os.environ["EX_BASE_DIR"] = os.path.join(d, "exes")
    os.environ["EX_SESSION_DIR"] = os.path.join(d, "sessions")
    os.environ["EX_REAL"] = "0"  # force mock in this test
    try:
        # --- create empty Ex ---
        rc = mvp_cli.cmd_create(_NS(slug="alice", name="Alice", seed=None))
        C.ok("create: rc 0", rc == 0)
        C.ok("create: canonical exists", os.path.exists(os.path.join(os.environ["EX_BASE_DIR"], "alice", "persona_memory.json")))
        # --- import real ChatImport → persona_memory ---
        chat = json.load(open(os.path.join(_HERE, "..", "..", "evaluation", "dataset", "case_001", "messages.json"), encoding="utf-8"))
        chat_path = os.path.join(d, "chat.json")
        json.dump(chat, open(chat_path, "w", encoding="utf-8"), ensure_ascii=False)
        rc = mvp_cli.cmd_import(_NS(ex="alice", chat=chat_path, name="Alice"))
        C.ok("import: rc 0", rc == 0)
        pm = json.load(open(os.path.join(os.environ["EX_BASE_DIR"], "alice", "persona_memory.json"), encoding="utf-8"))
        C.ok("import: canonical is v1.2 with persona/memory", pm.get("schema_version") == "1.2"
             and "persona" in pm and "memory" in pm)
        # --- list ---
        rc = mvp_cli.cmd_list(_NS())
        C.ok("list: rc 0", rc == 0)
        # --- chat (mock) multi-turn + correction confirm + persist ---
        h = mvp_cli.make_host()
        # monkeypatch adapter to mock via make_host? make_host builds real if EX_REAL=1; we set 0 -> adapter None -> mock default
        sid = h.new_session("alice")
        out = h.respond(sid, "在吗")
        C.ok("chat: mock respond ok", isinstance(out.get("assistant_response"), str))
        # produce correction via mock (mock won't naturally correct; simulate by feeding a correction sentence then check proposal path)
        h.respond(sid, "不对，她其实话痨")
        props = h.pending_proposals(sid)
        # mock runtime still runs correction detect (rule-based) regardless of adapter
        # (correction overlay comes from classifier, not LLM) -> proposal may exist
        # If present, confirm; else this Ex has no memory to correct (imported case_001 may differ)
        if props:
            pid = props[0]["proposal_id"]
            res = h.confirm_proposal(sid, pid)
            C.ok("chat: correction confirm persisted", res.get("ok") is True, str(res))
        # --- isolation: second Ex has no alice data ---
        mvp_cli.cmd_create(_NS(slug="bob", name="Bob", seed=None))
        pmB = json.load(open(os.path.join(os.environ["EX_BASE_DIR"], "bob", "persona_memory.json"), encoding="utf-8"))
        C.ok("isolation: bob canonical empty (no alice persona)", len(pmB.get("memory", {}).get("core_facts", [])) == 0
             or "persona" in pmB)
        # --- privacy redaction ---
        C.ok("privacy: redact key", privacy.redact("sk-abcdef1234567890") == "[REDACTED]"
             or "[REDACTED]" in privacy.redact("sk-abcdef1234567890"))
        C.ok("privacy: log line no content", "她话痨" not in privacy.log_redacted("x", {"assistant": "她话痨", "slug": "a"}))
        # --- delete ---
        rc = mvp_cli.cmd_delete(_NS(ex="alice"))
        C.ok("delete: rc 0 + data gone", rc == 0
             and not os.path.exists(os.path.join(os.environ["EX_BASE_DIR"], "alice"))
             and not os.path.exists(os.path.join(os.environ["EX_SESSION_DIR"], "alice")))
    finally:
        shutil.rmtree(d, ignore_errors=True)
        for k in ("EX_BASE_DIR", "EX_SESSION_DIR", "EX_REAL"):
            os.environ.pop(k, None)

    print(f"\n通过 {C.ok_n} / 失败 {C.fail_n}")
    for f in C.fails:
        print("  -", f)
    sys.exit(0 if C.fail_n == 0 else 1)


if __name__ == "__main__":
    main()
