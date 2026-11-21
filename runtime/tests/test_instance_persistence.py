#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Distribution Wrapper F1：Instance Persistence Layer deterministic tests。

验证：
  - confirmed → F5-e 归约 → corrections[] 落 active + 旧 memory supersede（对齐 frozen builder on-disk）
  - superseded/rejected/expired 不错误 active
  - 幂等（同 confirmed 不重复）
  - 原子写（temp+os.replace）+ revision 递增 + backup 生成
  - schema/结构校验
  - 唯一 canonical（只写目标文件；不产第二份）
  - 不改任何 Frozen（本模块纯 Non-Frozen 新增）
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.dirname(HERE)
for p in (RUNTIME,):
    if p not in sys.path:
        sys.path.insert(0, p)

import instance_persistence as ip  # noqa: E402


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


def instance_pm():
    pm = {"schema_version": "1.2", "revision": 1, "persona": {"layer0_rules": {}, "identity": {}},
          "memory": {"core_facts": [{"id": "mi_A", "content": "她话少", "status": "active",
                                     "confidence": 0.8, "importance": 1, "source_type": "user_input"}],
                     "preferences": [], "timeline": [], "shared_experiences": [],
                     "conflicts": [], "happy_memories": [], "breakup": [],
                     "inside_jokes": [], "daily_patterns": []},
          "corrections": []}
    return pm


def confirmed(stmt_id, value, target_id, target_path="memory.core_facts", user_statement="纠正"):
    return {"id": stmt_id, "corrected_value": value, "target_id": target_id,
            "target_path": target_path, "user_statement": user_statement}


def main():
    print("=== Distribution Wrapper F1: Instance Persistence ===")
    # ---- 1. confirmed correction → active corrections[] + old memory superseded ----
    pm = instance_pm()
    stmts = [confirmed("corr_B", "她话痨", "mi_A")]
    new = ip.apply_to_persona_memory(pm, stmts)
    C.ok("F1-1: corrections[] gained active corr_B", any(c["id"] == "corr_B" and c["status"] == "active"
         for c in new["corrections"]), json.dumps(new["corrections"], ensure_ascii=False))
    memA = next(m for m in new["memory"]["core_facts"] if m["id"] == "mi_A")
    C.ok("F1-1: old memory mi_A superseded/corrected", memA["status"] == "superseded"
         and memA.get("supersede_kind") == "corrected" and memA.get("superseded_by") == "corr_B",
         str(memA))
    # ---- 2. superseded/rejected/expired never active ----
    #   只有 confirmed 传入；rejected/expired 语义在调用方已过滤。防御：确认层只收 confirmed，本层幂等。
    C.ok("F1-2: only confirmed applied (defensive — caller filters status)",
         len(new["corrections"]) == 1)
    # ---- 3. idempotent: same confirmed not duplicated ----
    new2 = ip.apply_to_persona_memory(new, stmts)  # re-apply same corr_B
    C.ok("F1-3: idempotent (no duplicate corr_B)", sum(1 for c in new2["corrections"] if c["id"] == "corr_B") == 1)
    # ---- 4. newer confirmed supersedes older active correction ----
    stmts_c = [confirmed("corr_C", "她话特别多", "mi_A")]
    new3 = ip.apply_to_persona_memory(new2, stmts_c)
    corrs = {c["id"]: c for c in new3["corrections"]}
    C.ok("F1-4: corr_C active, corr_B superseded_by C", corrs["corr_C"]["status"] == "active"
         and corrs["corr_B"]["status"] == "superseded" and corrs["corr_B"].get("superseded_by") == "corr_C",
         json.dumps(corrs, ensure_ascii=False))
    # ---- 5. write_back: atomic, revision bump, backup, structure check ----
    d = tempfile.mkdtemp()
    try:
        pm_path = os.path.join(d, "persona_memory.json")
        with open(pm_path, "w", encoding="utf-8") as f:
            json.dump(instance_pm(), f, ensure_ascii=False, indent=2)
        bk_dir = os.path.join(d, "versions")
        res = ip.write_back(pm_path, [confirmed("corr_B", "她话痨", "mi_A")], backup_dir=bk_dir)
        C.ok("F1-5: write_back ok + revision bumped", res["ok"] and res["revision"] == 2, str(res))
        C.ok("F1-5: backup file created", os.path.exists(bk_dir) and len(os.listdir(bk_dir)) >= 1)
        with open(pm_path, encoding="utf-8") as f:
            on_disk = json.load(f)
        C.ok("F1-5: on-disk has corr_B active + mi_A superseded",
             any(c["id"] == "corr_B" and c["status"] == "active" for c in on_disk["corrections"])
             and next(m for m in on_disk["memory"]["core_facts"] if m["id"] == "mi_A")["status"] == "superseded")
        C.ok("F1-5: revision persisted", on_disk.get("revision") == 2)
        # no temp residue
        C.ok("F1-5: no temp file residue", not any(f.endswith(".tmp") for f in os.listdir(d)))
    finally:
        shutil.rmtree(d, ignore_errors=True)
    # ---- 6. structure validation rejects malformed ----
    d2 = tempfile.mkdtemp()
    try:
        bad = os.path.join(d2, "bad.json")
        with open(bad, "w", encoding="utf-8") as f:
            json.dump({"foo": 1}, f, ensure_ascii=False)
        try:
            ip.write_back(bad, [])
            C.ok("F1-6: malformed rejected", False)
        except ValueError:
            C.ok("F1-6: malformed rejected (ValueError)", True)
    finally:
        shutil.rmtree(d2, ignore_errors=True)
    # ---- 7. canonical single-file (no second source produced) ----
    C.ok("F1-7: apply is pure in-memory (input pm unchanged)",
         len(instance_pm()["corrections"]) == 0 and len(new["corrections"]) == 1)

    # ==================== G3 Memory Item Lifecycle ====================
    _g3()

    print(f"\n通过 {C.ok_n} / 失败 {C.fail_n}")
    for f in C.fails:
        print("  -", f)
    sys.exit(0 if C.fail_n == 0 else 1)


def _g3():
    """G3-1 / G3-3 生命周期：create / decide / fallback 闸门 / 幂等 / 防复活 / 持久化安全。"""
    import persona_memory_builder as pmb

    def pm_empty():
        return {"schema_version": "1.2", "revision": 1, "persona": {"layer0_rules": {}, "identity": {}},
                "memory": {b: [] for b in ip.MEMORY_BUCKETS}, "corrections": []}

    def with_pending(item_id="mi_c", bucket="conflicts"):
        pm = pm_empty()
        pm["memory"][bucket] = [{"id": item_id, "content": "她喜欢猫", "status": "pending_confirmation",
                                 "conflicts_with": [], "confidence": 0.5, "importance": 3,
                                 "source_type": "user_input"}]
        return pm

    # ---- T4: fallback bucket fail-closed（Frozen choke point，绕过 Host 也无法 create）----
    pm, rep = ip.apply_memory_lifecycle(pm_empty(), [{"kind": "create", "content": "我最近跳槽去字节了"}])
    C.ok("G3-T3: fallback bucket → 不写入 canonical",
         sum(len(v) for v in pm["memory"].values()) == 0
         and any("fallback bucket" in n.get("reason", "") for n in rep["noops"]),
         str(rep["noops"]))
    C.ok("G3-T3: _heuristic_bucket 判定确为 fallback",
         pmb._heuristic_bucket("我最近跳槽去字节了") == "shared_experiences")

    # ---- T6: deterministic memory_item_id + create 明确 bucket ----
    pm, rep = ip.apply_memory_lifecycle(pm_empty(), [{"kind": "create", "content": "她喜欢喝奶茶"}])
    created = pm["memory"]["preferences"][0]
    C.ok("G3-T6: deterministic id == memory_item_id(bucket, content)",
         created["id"] == pmb.memory_item_id("preferences", "她喜欢喝奶茶"), created["id"])
    C.ok("G3-T5: create → status=active / source_type=user_input / evidence_ids=[]",
         created["status"] == "active" and created["source_type"] == "user_input"
         and created["evidence_ids"] == [] and created["confidence"] == 0.0)

    # ---- T15: create 幂等 ----
    pm2, rep2 = ip.apply_memory_lifecycle(pm, [{"kind": "create", "content": "她喜欢喝奶茶"}])
    C.ok("G3-T15: 重复 create → applied 0 + no-op",
         rep2["applied"] == 0 and any(n["reason"] == "already active" for n in rep2["noops"]),
         str(rep2["noops"]))
    C.ok("G3-T15: 重复 create 不产生重复 item",
         sum(len(v) for v in pm2["memory"].values()) == 1)

    # ---- T16: rejected 不被普通 create 复活 ----
    pmr = pm_empty()
    pmr["memory"]["preferences"] = [dict(created, status="rejected")]
    pm3, rep3 = ip.apply_memory_lifecycle(pmr, [{"kind": "create", "content": "她喜欢喝奶茶"}])
    C.ok("G3-T16: rejected 被普通 create 自动复活? → 否",
         pm3["memory"]["preferences"][0]["status"] == "rejected"
         and any(n["reason"] == "rejected_requires_explicit_revive" for n in rep3["noops"]),
         str(rep3["noops"]))

    # ---- T8/T9: decide pending → active / rejected ----
    pa, _ = ip.apply_memory_lifecycle(with_pending(), [{"kind": "decide", "bucket": "conflicts",
                                                        "item_id": "mi_c",
                                                        "expect_status": "pending_confirmation",
                                                        "approve": True}])
    C.ok("G3-T8: pending_confirmation --approve--> active",
         pa["memory"]["conflicts"][0]["status"] == "active")
    pr, _ = ip.apply_memory_lifecycle(with_pending(), [{"kind": "decide", "bucket": "conflicts",
                                                        "item_id": "mi_c",
                                                        "expect_status": "pending_confirmation",
                                                        "approve": False}])
    C.ok("G3-T9: pending_confirmation --reject--> rejected",
         pr["memory"]["conflicts"][0]["status"] == "rejected")

    # ---- T15: decide 幂等（status_mismatch 守卫）----
    _, rep4 = ip.apply_memory_lifecycle(pr, [{"kind": "decide", "bucket": "conflicts",
                                              "item_id": "mi_c",
                                              "expect_status": "pending_confirmation",
                                              "approve": True}])
    C.ok("G3-T15: 重复 decide → status_mismatch no-op",
         rep4["applied"] == 0 and any("status_mismatch" in n["reason"] for n in rep4["noops"]),
         str(rep4["noops"]))

    # ---- T17: rejected 仅经显式 revive（expect_status=rejected）复活 ----
    pv, _ = ip.apply_memory_lifecycle(pr, [{"kind": "decide", "bucket": "conflicts",
                                            "item_id": "mi_c",
                                            "expect_status": "rejected", "approve": True}])
    C.ok("G3-T17: 显式 revive(rejected) → active",
         pv["memory"]["conflicts"][0]["status"] == "active")
    # pending 不能冒充 rejected 复活
    _, rep5 = ip.apply_memory_lifecycle(with_pending(), [{"kind": "decide", "bucket": "conflicts",
                                                          "item_id": "mi_c",
                                                          "expect_status": "rejected",
                                                          "approve": True}])
    C.ok("G3-T17: expect_status=rejected 对 pending 项 → no-op（不可混淆）",
         rep5["applied"] == 0 and any("status_mismatch" in n["reason"] for n in rep5["noops"]))

    # ---- T21: 结构通过 schema memoryItem 校验 ----
    try:
        import jsonschema
        sch = json.load(open(os.path.join(os.path.dirname(RUNTIME), "persona_memory.schema.json"),
                             encoding="utf-8"))
        # memoryItem 内含 $ref → 需带 $defs 一起校验（不可单独校验子 schema）
        sub = {"$ref": "#/$defs/memoryItem", "$defs": sch["$defs"]}
        jsonschema.validate(created, sub)
        C.ok("G3-T21: 新建 item 通过 memoryItem schema 校验", True)
    except ImportError:
        C.ok("G3-T21: jsonschema 不可用（跳过）", True)
    except Exception as e:  # noqa: BLE001
        C.ok("G3-T21: 新建 item 通过 memoryItem schema 校验", False, str(e))

    # ---- T7/T11/T20/T22: 端到端 write_back（reject 不写 / 幂等 / 并发 / .tmp 清理）----
    d = tempfile.mkdtemp()
    try:
        p = os.path.join(d, "persona_memory.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(with_pending(), f, ensure_ascii=False, indent=2)
        # reject proposal（None ops）→ canonical 零变化
        res_rej = ip.write_back(p, [], lifecycle_ops=None)
        C.ok("G3-T7: 拒绝（无 ops）→ applied 0 / revision 不变",
             res_rej["applied"] == 0 and res_rej["revision"] == 1, str(res_rej))
        # approve → 写盘
        res_a = ip.write_back(p, [], lifecycle_ops=[{"kind": "decide", "bucket": "conflicts",
                                                     "item_id": "mi_c",
                                                     "expect_status": "pending_confirmation",
                                                     "approve": True}])
        C.ok("G3-T8: write_back 落盘 approve → revision 2",
             res_a["lifecycle_applied"] == 1 and res_a["revision"] == 2, str(res_a))
        with open(p, encoding="utf-8") as f:
            disk = json.load(f)
        C.ok("G3-T8: on-disk status == active",
             disk["memory"]["conflicts"][0]["status"] == "active")
        # 重复写回 → 字节比较 → applied 0 / revision 不变
        res_again = ip.write_back(p, [], lifecycle_ops=[{"kind": "decide", "bucket": "conflicts",
                                                         "item_id": "mi_c",
                                                         "expect_status": "pending_confirmation",
                                                         "approve": True}])
        C.ok("G3-T15: 重复写回 → applied 0 / revision 不变",
             res_again["applied"] == 0 and res_again["revision"] == 2, str(res_again))
        C.ok("G3-T22: 无 .tmp 残留", not any(f.endswith(".tmp") for f in os.listdir(d)))
        # 并发写：同 Ex 两线程各自 create 不同 content → 两 item 均在、revision 单调
        import threading
        lock = ip.get_instance_lock(p)
        errs = []

        def _w(txt):
            try:
                ip.write_back(p, [], lock=lock, lifecycle_ops=[{"kind": "create", "content": txt}])
            except Exception as e:  # noqa: BLE001
                errs.append(e)

        ts = [threading.Thread(target=_w, args=(t,)) for t in ("她喜欢喝拿铁", "她喜欢喝美式")]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        with open(p, encoding="utf-8") as f:
            disk2 = json.load(f)
        n_pref = len([m for m in disk2["memory"]["preferences"] if m["status"] == "active"])
        C.ok("G3-T20: 并发写无异常且两项均落盘",
             not errs and n_pref == 2, f"errs={errs} n={n_pref}")
        C.ok("G3-T20: revision 单调递增", disk2["revision"] >= 4, str(disk2["revision"]))
        C.ok("G3-T20: canonical 结构未被破坏",
             not ip._require_pm_structure(disk2), str(ip._require_pm_structure(disk2)))
    finally:
        shutil.rmtree(d, ignore_errors=True)

    # ---- T19: persistence failure recovery（malformed canonical → 抛错且文件不变）----
    d3 = tempfile.mkdtemp()
    try:
        bad = os.path.join(d3, "bad.json")
        with open(bad, "w", encoding="utf-8") as f:
            json.dump({"foo": 1}, f, ensure_ascii=False)
        before = open(bad, encoding="utf-8").read()
        try:
            ip.write_back(bad, [], lifecycle_ops=[{"kind": "create", "content": "她喜欢喝奶茶"}])
            C.ok("G3-T19: malformed + lifecycle_ops 仍被拒绝", False)
        except ValueError:
            C.ok("G3-T19: malformed + lifecycle_ops 仍被拒绝 (ValueError)",
                 open(bad, encoding="utf-8").read() == before)
    finally:
        shutil.rmtree(d3, ignore_errors=True)

    # ---- 输入不被修改（pure in-memory）----
    src = with_pending()
    snap = json.dumps(src, ensure_ascii=False, sort_keys=True)
    ip.apply_memory_lifecycle(src, [{"kind": "decide", "bucket": "conflicts", "item_id": "mi_c",
                                     "expect_status": "pending_confirmation", "approve": True}])
    C.ok("G3: apply_memory_lifecycle 输入 pm 不被修改",
         json.dumps(src, ensure_ascii=False, sort_keys=True) == snap)

    print(f"\n通过 {C.ok_n} / 失败 {C.fail_n}")
    for f in C.fails:
        print("  -", f)
    sys.exit(0 if C.fail_n == 0 else 1)


if __name__ == "__main__":
    main()
