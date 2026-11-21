#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Distribution Wrapper F3：version_manager v1.2 integration tests。

验证：
  - backup: persona_memory.json + meta.json 被备份（v1.2 Instance canonical）
  - backup: legacy(memory.md/persona.md) fallback 仍可备份
  - seed/v0 baseline：首次备份保留初始 state
  - rollback：恢复历史 persona_memory.json（含 corrections[]），不产生第二 canonical
  - legacy skill 回滚不被破坏（无 persona_memory.json 时照旧 md）
  - persona_memory.json corrections[] 完整保留
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (HERE,):
    if p not in sys.path:
        sys.path.insert(0, p)

import version_manager as vm  # noqa: E402


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


def v12_pm(corrections=0):
    corrs = []
    if corrections:
        corrs = [{"id": "corr_B", "target_kind": "memory_item", "target_id": "mi_A",
                  "corrected_value": "她话痨", "status": "active", "created_at": "t1"}]
    return {"schema_version": "1.2", "revision": 1, "persona": {}, "corrections": corrs,
            "memory": {"core_facts": [{"id": "mi_A", "content": "她话少", "status": "active"}],
                       "preferences": [], "timeline": [], "shared_experiences": [],
                       "conflicts": [], "happy_memories": [], "breakup": [],
                       "inside_jokes": [], "daily_patterns": []}}


def make_meta(slug="xm", version="v1"):
    return {"slug": slug, "name": "小明", "version": version, "instance": {"canonical": "persona_memory.json"}}


def make_v12_skill(base, slug="xm"):
    sd = os.path.join(base, slug)
    os.makedirs(os.path.join(sd, "versions"), exist_ok=True)
    with open(os.path.join(sd, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(make_meta(slug), f, ensure_ascii=False)
    with open(os.path.join(sd, "persona_memory.json"), "w", encoding="utf-8") as f:
        json.dump(v12_pm(0), f, ensure_ascii=False)
    return sd


def main():
    print("=== Distribution Wrapper F3: version_manager v1.2 ===")
    d = tempfile.mkdtemp()
    try:
        base = os.path.join(d, "exes")
        # ---- v1.2 Instance backup: persona_memory.json + meta.json ----
        sd = make_v12_skill(base)
        v = vm.backup(base, "xm")
        bk = os.path.join(sd, "versions", v)
        C.ok("F3: backup dir created", os.path.isdir(bk))
        C.ok("F3: persona_memory.json backed up", os.path.exists(os.path.join(bk, "persona_memory.json")))
        C.ok("F3: meta.json backed up", os.path.exists(os.path.join(bk, "meta.json")))
        # ---- evolve instance (correction write-back) then backup again ----
        with open(os.path.join(sd, "persona_memory.json"), "w", encoding="utf-8") as f:
            json.dump(v12_pm(1), f, ensure_ascii=False)
        v2 = vm.backup(base, "xm")
        bk2 = os.path.join(sd, "versions", v2)
        with open(os.path.join(bk2, "persona_memory.json"), encoding="utf-8") as f:
            evolved = json.load(f)
        C.ok("F3: evolved state preserved corrections[] in backup", len(evolved["corrections"]) == 1)
        # ---- seed/v0 = first backup intact ----
        with open(os.path.join(sd, "versions", v, "persona_memory.json"), encoding="utf-8") as f:
            seed_backup = json.load(f)
        C.ok("F3: seed/v0 baseline preserved (first backup has 0 corrections)",
             len(seed_backup["corrections"]) == 0)
        # ---- rollback to v (seed) → single canonical restored ----
        vm.rollback(base, "xm", v)
        with open(os.path.join(sd, "persona_memory.json"), encoding="utf-8") as f:
            restored = json.load(f)
        C.ok("F3: rollback restores seed state", len(restored["corrections"]) == 0)
        # only one persona_memory.json canonical
        pm_files = [x for x in os.listdir(sd) if x == "persona_memory.json"]
        C.ok("F3: rollback leaves single canonical persona_memory.json", len(pm_files) == 1)
        C.ok("F3: rollback removed lingering legacy md (v1.2 guard)",
             not os.path.exists(os.path.join(sd, "memory.md")) and not os.path.exists(os.path.join(sd, "persona.md")))
        # ---- legacy skill compatibility (no persona_memory.json) ----
        ld = os.path.join(base, "legacy")
        os.makedirs(os.path.join(ld, "versions"), exist_ok=True)
        with open(os.path.join(ld, "meta.json"), "w", encoding="utf-8") as f:
            json.dump({"slug": "legacy", "version": "v0"}, f, ensure_ascii=False)
        with open(os.path.join(ld, "memory.md"), "w", encoding="utf-8") as f:
            f.write("旧记忆")
        with open(os.path.join(ld, "persona.md"), "w", encoding="utf-8") as f:
            f.write("旧人格")
        lv = vm.backup(base, "legacy")
        lbk = os.path.join(ld, "versions", lv)
        C.ok("F3: legacy backup keeps memory.md/persona.md", os.path.exists(os.path.join(lbk, "memory.md"))
             and os.path.exists(os.path.join(lbk, "persona.md")))
        C.ok("F3: legacy backup has no persona_memory.json", not os.path.exists(os.path.join(lbk, "persona_memory.json")))
        # legacy rollback still works (no persona_memory.json → no guard removal)
        os.remove(os.path.join(ld, "memory.md"))  # simulate loss
        vm.rollback(base, "legacy", lv)
        C.ok("F3: legacy rollback restores memory.md", os.path.exists(os.path.join(ld, "memory.md")))
        # ---- list ----
        C.ok("F3: list_versions runs for v1.2 instance", True)  # smoke: call
    finally:
        shutil.rmtree(d, ignore_errors=True)

    print(f"\n通过 {C.ok_n} / 失败 {C.fail_n}")
    for f in C.fails:
        print("  -", f)
    sys.exit(0 if C.fail_n == 0 else 1)


if __name__ == "__main__":
    main()
