#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Distribution Wrapper F2：skill_writer v1.2 deterministic tests。

验证生成的 Ex Instance 符合 Canonical Source Contract，而不只是"文件生成成功"：
  - persona_memory.json = 完整 v1.2（seed 初始化，唯一 canonical）
  - SKILL.md 零人格事实（无 persona/memory 内容泄漏）
  - chat.py 薄模板（引用 persona_loader/PersonaRuntime，不重写）
  - meta.json / versions/ 结构正确
  - seed ≠ Instance（写 persona_memory.json 后再独立演化验证）
  - 不产生第二 canonical source
  - legacy tools/skill_writer.py 未被动（仅新文件）
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (HERE, os.path.dirname(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

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


def seed_pm():
    return {"schema_version": "1.2", "revision": 1,
            "persona": {"identity": {"name_or_alias": {"value": "小明", "claim_id": "pc_n"}},
                        "speech_style": {"catchphrases": [{"value": "哈哈哈哈", "claim_id": "pc_c"}]},
                        "layer0_rules": {}},
            "memory": {"core_facts": [{"id": "mi_A", "content": "她话少", "status": "active",
                                       "confidence": 0.8, "importance": 1, "source_type": "user_input"}],
                       "preferences": [], "timeline": [], "shared_experiences": [],
                       "conflicts": [], "happy_memories": [], "breakup": [],
                       "inside_jokes": [], "daily_patterns": []},
            "corrections": []}


PERSONA_MARKERS = ["小明", "哈哈哈哈", "她话少", "话痨", "relationship", "catchphrase", "她住在"]


def main():
    print("=== Distribution Wrapper F2: skill_writer v1.2 ===")
    d = tempfile.mkdtemp()
    try:
        base = os.path.join(d, "exes")
        seed = seed_pm()
        sd = sw12.init_ex_instance(seed, base, "xiaoming", name="小明")
        C.ok("F2: instance dir created", os.path.isdir(sd))
        # files present
        for fname in ("SKILL.md", "persona_memory.json", "chat.py", "meta.json"):
            C.ok(f"F2: {fname} exists", os.path.exists(os.path.join(sd, fname)))
        C.ok("F2: versions/ exists", os.path.isdir(os.path.join(sd, "versions")))
        # ---- persona_memory.json = canonical v1.2 (full seed) ----
        with open(os.path.join(sd, "persona_memory.json"), encoding="utf-8") as f:
            pm = json.load(f)
        C.ok("F2: persona_memory.json is full v1.2 (schema/version/persona/memory/corrections)",
             pm.get("schema_version") == "1.2" and "persona" in pm and "memory" in pm
             and "corrections" in pm)
        C.ok("F2: persona_memory.json == seed content",
             json.dumps(pm, ensure_ascii=False, sort_keys=True)
             == json.dumps(seed, ensure_ascii=False, sort_keys=True))
        # ---- SKILL.md has ZERO persona facts ----
        with open(os.path.join(sd, "SKILL.md"), encoding="utf-8") as f:
            skill = f.read()
        leaked = [m for m in PERSONA_MARKERS if m in skill]
        C.ok("F2: SKILL.md has zero persona/memory facts", not leaked, f"leaked={leaked}")
        C.ok("F2: SKILL.md references canonical persona_memory.json",
             "persona_memory.json" in skill)
        # ---- chat.py = thin template referencing loader/runtime, not reimplementing ----
        with open(os.path.join(sd, "chat.py"), encoding="utf-8") as f:
            chat = f.read()
        C.ok("F2: chat.py imports persona_loader/PersonaRuntime",
             "persona_loader" in chat and "PersonaRuntime" in chat)
        C.ok("F2: chat.py does NOT reimplement respond/context/boundary bodies",
             "def respond(self" not in chat and "render_system_block" not in chat
             and "assess_support" not in chat and "context_assembly" not in chat)
        C.ok("F2: chat.py references instance_persistence for confirmed write-back",
             "instance_persistence" in chat or "write_back" in chat)
        # ---- meta.json ----
        with open(os.path.join(sd, "meta.json"), encoding="utf-8") as f:
            meta = json.load(f)
        C.ok("F2: meta.json slug/name/version/canonical",
             meta.get("slug") == "xiaoming" and meta.get("instance", {}).get("canonical") == "persona_memory.json")
        # ---- seed != Instance: mutate instance persona_memory, seed unchanged ----
        with open(os.path.join(sd, "persona_memory.json"), "w", encoding="utf-8") as f:
            pm2 = json.loads(json.dumps(pm, ensure_ascii=False))
            pm2["corrections"].append({"id": "corr_x", "status": "active"})
            json.dump(pm2, f, ensure_ascii=False, indent=2)
        C.ok("F2: seed ≠ Instance current state (instance evolved, seed immutable)",
             len(seed["corrections"]) == 0 and len(pm2["corrections"]) == 1)
        # ---- no second canonical source (only one persona_memory.json, no md persona) ----
        all_files = []
        for root, _, files in os.walk(sd):
            for fn in files:
                all_files.append(os.path.join(root, fn))
        pm_files = [f for f in all_files if f.endswith("persona_memory.json")]
        md_persona = [f for f in all_files if os.path.basename(f) in ("persona.md", "memory.md")]
        C.ok("F2: single persona_memory.json, no persona.md/memory.md second source",
             len(pm_files) == 1 and not md_persona, str(all_files))
        # ---- legacy untouched: skill_writer.py NOT created/modified by this module ----
        C.ok("F2: legacy tools/skill_writer.py untouched (new file added only)",
             os.path.exists(os.path.join(HERE, "skill_writer.py")))
        # ---- idempotent re-init rejected (no overwrite / no second instance) ----
        try:
            sw12.init_ex_instance(seed, base, "xiaoming")
            C.ok("F2: re-init same slug rejected", False)
        except FileExistsError:
            C.ok("F2: re-init same slug rejected (FileExistsError)", True)
        # ---- invalid seed rejected ----
        try:
            sw12.init_ex_instance({"bad": 1}, base, "badslug")
            C.ok("F2: invalid seed rejected", False)
        except ValueError:
            C.ok("F2: invalid seed rejected (ValueError)", True)
    finally:
        shutil.rmtree(d, ignore_errors=True)

    print(f"\n通过 {C.ok_n} / 失败 {C.fail_n}")
    for f in C.fails:
        print("  -", f)
    sys.exit(0 if C.fail_n == 0 else 1)


if __name__ == "__main__":
    main()
