#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Distribution Wrapper F4：chat.py runtime wiring + Instance-level shared lock tests。

验证：
  1. instance_persistence.get_instance_lock(path)：同一路径稳定返回同一 Lock（多 session 共享）。
  2. 不同 Instance 路径 → 不同 Lock（Instance 隔离）。
  3. skill_writer_v12 生成的 chat.py 模板引用 get_instance_lock/persist_confirmed（稳定锁路径），
     且不重实现 PersonaRuntime/correction。
  4. write_back 用共享锁端到端可跑（confirmed → persona_memory.json 落盘）。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.dirname(HERE)
TOOLS = os.path.dirname(RUNTIME) + "/tools"
for p in (RUNTIME, TOOLS):
    if p not in sys.path:
        sys.path.insert(0, p)

import instance_persistence as ip  # noqa: E402
import skill_writer_v12 as sw12  # noqa: E402


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


def v12_pm():
    return {"schema_version": "1.2", "revision": 1,
            "persona": {"identity": {"name_or_alias": {"value": "小明"}}, "layer0_rules": {}},
            "memory": {"core_facts": [{"id": "mi_A", "content": "她话少", "status": "active",
                                       "confidence": 0.8, "importance": 1, "source_type": "user_input"}],
                       "preferences": [], "timeline": [], "shared_experiences": [],
                       "conflicts": [], "happy_memories": [], "breakup": [],
                       "inside_jokes": [], "daily_patterns": []},
            "corrections": []}


def main():
    print("=== Distribution Wrapper F4: chat.py wiring + shared lock ===")
    # ---- 1. stable per-path lock (multi-session share) ----
    l1 = ip.get_instance_lock("/ex/a/persona_memory.json")
    l2 = ip.get_instance_lock("/ex/a/persona_memory.json")
    C.ok("F4: same instance path → same lock (stable across calls/sessions)", l1 is l2)
    # ---- 2. different instance path → different lock ----
    l3 = ip.get_instance_lock("/ex/b/persona_memory.json")
    C.ok("F4: different instance path → different lock (isolation)", l1 is not l3)
    # ---- 3. chat.py template (from skill_writer_v12) references shared lock ----
    d = tempfile.mkdtemp()
    try:
        base = os.path.join(d, "exes")
        sd = sw12.init_ex_instance(v12_pm(), base, "xm")
        with open(os.path.join(sd, "chat.py"), encoding="utf-8") as f:
            chat = f.read()
        C.ok("F4: chat.py imports persona_loader/PersonaRuntime",
             "persona_loader" in chat and "PersonaRuntime" in chat)
        C.ok("F4: chat.py references get_instance_lock (stable shared lock)",
             "get_instance_lock" in chat and "persist_confirmed" in chat, "")
        C.ok("F4: chat.py does NOT reimplement runtime",
             "def respond(self" not in chat and "assess_support" not in chat
             and "resolve_statements" not in chat)
        # ---- 4. write_back with shared lock end-to-end ----
        pm_path = os.path.join(sd, "persona_memory.json")
        confirmed = [{"id": "corr_B", "corrected_value": "她话痨", "target_id": "mi_A",
                      "target_path": "memory.core_facts", "user_statement": "纠正", "created_at": "t1"}]
        lock = ip.get_instance_lock(pm_path)
        res = ip.write_back(pm_path, confirmed, backup_dir=os.path.join(sd, "versions"), lock=lock)
        C.ok("F4: write_back via shared lock ok + revision bump", res["ok"] and res["revision"] == 2, str(res))
        with open(pm_path, encoding="utf-8") as f:
            on_disk = json.load(f)
        C.ok("F4: confirmed correction persisted to canonical",
             any(c["id"] == "corr_B" and c["status"] == "active" for c in on_disk["corrections"]))
        # same lock reused by a "second session" (structural share)
        lock2 = ip.get_instance_lock(pm_path)
        C.ok("F4: second session reuses same lock object", lock is lock2)
    finally:
        shutil.rmtree(d, ignore_errors=True)

    print(f"\n通过 {C.ok_n} / 失败 {C.fail_n}")
    for f in C.fails:
        print("  -", f)
    sys.exit(0 if C.fail_n == 0 else 1)


if __name__ == "__main__":
    main()
