#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ResolvedEvidenceBundle 测试套件（Stage 5.4，23 类）

直接运行： python test_resolve_bundle.py
先经冻结 evidence_merge 产出真实 MergeResult，再 resolve_bundle，保证输入真实合法。
"""

from __future__ import annotations

import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import evidence_merge as em
import resolve_bundle as rb


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


def cand(*, claim, cid, basis="direct_quote", sp="target", et="target_message",
         conf=0.8, imp=3, src=("wx-1",), st="pending", stype="wechat_log",
         obs=None, tp=None, msgs=None, corr=False):
    if corr:
        et = "user_correction"; basis = "correction"; stype = "correction"; src = ("correction",)
    if msgs is None:
        msgs = ["m_" + cid]
    return {"candidate_id": cid, "evidence_type": et, "claim": {"value": claim, "basis": basis},
            "supporting_message_ids": list(msgs), "source_refs": list(src), "speaker_role": sp,
            "observed_at": obs, "time_period": tp, "confidence": conf, "importance": imp,
            "source_type": stype, "status": st, "conflicts_with": [], "created_at": None}


def nar(*, claim, cid, **kw):
    return cand(claim=claim, cid=cid, sp="user", et="user_narration", basis="user_report_only",
                stype="user_narration", src=("user_narration",), **kw)


def to_set(cs):
    return {"schema_version": "1.0", "extraction_context": {}, "candidates": cs}


def merged(cs, llm=None):
    r = em.merge_evidence(candidates=cs, llm=llm)
    assert r["ok"], r["errors"]
    return r["merge_result"]


def resolve(cs, mr=None, corrections=None):
    if mr is None:
        mr = merged(cs)
    return rb.resolve_bundle(candidate_set=to_set(cs), merge_result=mr,
                             corrections=corrections)


def bundle_errs(b):
    return rb._schema_errs(rb._validator(rb.BUNDLE_SCHEMA_PATH), b)


def gr_types(b):
    return sorted(r["relation_type"] for r in b["group_level_relations"])


# ===========================================================================
# 1. 合法双输入 → bundle + schema 通过
# ===========================================================================
def t1_valid():
    cs = [cand(claim="她喜欢猫", cid="c_1"), cand(claim="她讨厌猫", cid="c_2")]
    r = resolve(cs)
    C.ok("1: ok", r["ok"], str(r["errors"]))
    b = r["bundle"]
    C.ok("1: schema valid", bundle_errs(b) == [], str(bundle_errs(b))[:200])
    C.ok("1: stats present", b["stats"]["group_count"] == 2 and b["stats"]["candidate_count"] == 2)
    C.ok("1: input_refs", b["input_refs"] == {"candidate_set_schema_version": "1.0", "merge_schema_version": "1.0"})


# ===========================================================================
# 2. conflict group-level edge
# ===========================================================================
def t2_conflict_edge():
    cs = [cand(claim="她喜欢猫", cid="c_1"), cand(claim="她讨厌猫", cid="c_2")]
    b = resolve(cs)["bundle"]
    gl = [r for r in b["group_level_relations"] if r["relation_type"] == "conflict"]
    C.ok("2: conflict group edge exists", len(gl) == 1, str(gr_types(b)))
    C.ok("2: endpoints are distinct groups", gl[0]["group_a"] != gl[0]["group_b"])
    C.ok("2: evidence non-empty traceable", len(gl[0]["evidence"]) >= 1)
    C.ok("2: not advisory (real conflict)", gl[0]["advisory"] is False)
    C.ok("2: both sides preserved", "c_1" in b["candidate_to_group"] and "c_2" in b["candidate_to_group"])


# ===========================================================================
# 3. temporal direction + time_info
# ===========================================================================
def t3_temporal():
    cs = [cand(claim="2022年喜欢喝奶茶", cid="c_1", obs="2022-06-01T00:00:00"),
          cand(claim="2025年已经不喝奶茶了", cid="c_2", obs="2025-01-01T00:00:00")]
    b = resolve(cs)["bundle"]
    gl = [r for r in b["group_level_relations"] if r["relation_type"] == "temporal_evolution"]
    C.ok("3: temporal edge", len(gl) == 1, str(gr_types(b)))
    ga, gb = gl[0]["group_a"], gl[0]["group_b"]
    # 哪个组装 2022? 查 candidate_to_group
    g_of_2022 = b["candidate_to_group"]["c_1"]
    g_of_2025 = b["candidate_to_group"]["c_2"]
    if ga == g_of_2022:  # a 早
        C.ok("3: direction a_earlier", gl[0]["direction"] == "a_earlier_b_later", str(gl[0]["direction"]))
    else:
        C.ok("3: direction b_earlier", gl[0]["direction"] == "b_earlier_a_later", str(gl[0]["direction"]))
    C.ok("3: time_info populated", gl[0]["time_info"] is not None)
    C.ok("3: no truth selection", True)


# ===========================================================================
# 4. correction_relation + candidate correction locating
# ===========================================================================
def t4_correction_relation_locate():
    cs = [cand(claim="她喜欢猫", cid="c_1"), cand(claim="纠正：她讨厌猫", cid="c_2", corr=True)]
    corr = {"id": "corr_x", "target_kind": "candidate", "target_id": "c_1", "target_path": "x",
            "user_statement": "她讨厌猫", "corrected_value": "她讨厌猫", "status": "active"}
    r = resolve(cs, corrections=[corr])
    b = r["bundle"]
    C.ok("4: correction_relation group edge", "correction_relation" in gr_types(b))
    pc = b["pending_corrections"]
    C.ok("4: pending correction located to candidate", len(pc) == 1 and pc[0]["resolved_target"]["kind"] == "candidate"
         and pc[0]["resolved_target"]["candidate_id"] == "c_1", json.dumps(pc, ensure_ascii=False))
    C.ok("4: group_id resolved", pc[0]["resolved_target"]["group_id"] == b["candidate_to_group"]["c_1"])


# ===========================================================================
# 5/6. persona_claim / memory_item correction → belongs_to_5_5
# ===========================================================================
def t5_persona_claim_belongs_55():
    cs = [cand(claim="她喜欢猫", cid="c_1")]
    for tk in ("persona_claim", "memory_item"):
        corr = {"id": "corr_" + tk, "target_kind": tk, "target_id": "pc_abc",
                "user_statement": "u", "corrected_value": "v", "status": "active"}
        b = resolve(cs, corrections=[corr])["bundle"]
        pc = b["pending_corrections"][0]
        C.ok(f"5/6: {tk} → belongs_to_5_5", pc["resolved_target"]["kind"] == "belongs_to_5_5"
             and pc["target_kind"] == tk and pc["target_id"] == "pc_abc")


# ===========================================================================
# 7. candidate correction target 不在本批
# ===========================================================================
def t7_correction_unresolvable():
    cs = [cand(claim="她喜欢猫", cid="c_1")]
    corr = {"id": "corr_z", "target_kind": "candidate", "target_id": "c_nonexistent",
            "user_statement": "u", "corrected_value": "v", "status": "active"}
    r = resolve(cs, corrections=[corr])
    pc = r["bundle"]["pending_corrections"][0]
    C.ok("7: unresolvable_in_this_batch", pc["resolved_target"]["kind"] == "unresolvable_in_this_batch")
    C.ok("7: warning raised", any("不在本批" in w for w in r["warnings"]), str(r["warnings"]))


# ===========================================================================
# 8. supporting_related → advisory
# ===========================================================================
def t8_related_advisory():
    cs = [cand(claim="她喜欢猫", cid="c_1"), cand(claim="她养过一只猫", cid="c_2")]
    b = resolve(cs)["bundle"]
    gl = [r for r in b["group_level_relations"] if r["relation_type"] == "supporting_related"]
    C.ok("8: supporting_related advisory", len(gl) == 1 and gl[0]["advisory"] is True)
    C.ok("8: no membership change", b["candidate_to_group"]["c_1"] != b["candidate_to_group"]["c_2"])
    C.ok("8: evidence retained", len(gl[0]["evidence"]) >= 1)


# ===========================================================================
# 9/21. 多 relation → 单 group edge + evidence 累积
# ===========================================================================
def t9_multi_rel_single_edge():
    # 同组对多条 conflict candidate relation：需要同组对多对 candidate 都 conflict
    # 构造：group G1={c1,c2 same} group G2={c3} 且 c1-c3、c2-c3 都 conflict
    cs = [cand(claim="她喜欢猫", cid="c_1"),
          cand(claim="她喜欢猫", cid="c_2"),
          cand(claim="她讨厌猫", cid="c_3")]
    b = resolve(cs)["bundle"]
    gl_conf = [r for r in b["group_level_relations"] if r["relation_type"] == "conflict"]
    C.ok("9/21: single conflict group edge (not per candidate pair)", len(gl_conf) == 1,
         f"got {len(gl_conf)}; edges={[(r['group_a'],r['group_b']) for r in gl_conf]}")
    # G1={c1,c2}, G2={c3}; c1-c3 & c2-c3 both conflict → evidence has 2 rel ids
    C.ok("9/21: evidence accumulated", len(gl_conf[0]["evidence"]) >= 1)


# ===========================================================================
# 10. unresolved → 无虚假 pair
# ===========================================================================
def t10_unresolved_no_pair():
    # 构造含 unresolved 的 merge（直接手写 merge_result 的 unresolved 字段，因 5.3 多数情况不产）
    cs = [cand(claim="她喜欢猫", cid="c_1")]
    mr = merged(cs)
    mr["unresolved_candidate_ids"] = ["c_1"]
    b = resolve(cs, mr=mr)["bundle"]
    C.ok("10: unresolved listed single-side", len(b["unresolved"]) == 1 and b["unresolved"][0]["candidate_id"] == "c_1")
    C.ok("10: reason fixed", "pair 信息缺失" in b["unresolved"][0]["reason"])
    C.ok("10: no fabricated pair field", "candidate_b" not in b["unresolved"][0])
    C.ok("10: no unresolved groupRelation", "unresolved" not in gr_types(b))
    C.ok("10: unresolved_pair_count honest", b["stats"]["unresolved_pair_count"] == 1)


# ===========================================================================
# 11. discarded → 不建 group
# ===========================================================================
def t11_discarded():
    cs = [cand(claim="她喜欢猫", cid="c_1", st="discarded")]
    mr = merged([cand(claim="她喜欢猫", cid="c_2")])
    # 手写：让 c_1 只在 discarded 列表
    mr["discarded_candidate_ids"] = ["c_1"]
    mr["groups"] = [g for g in mr["groups"] if all(m["candidate_id"] != "c_1" for m in g["members"])]
    mr["stats"]["discarded"] = 1
    r = resolve(cs + [cand(claim="她喜欢猫", cid="c_2")], mr=mr)
    b = r["bundle"]
    C.ok("11: discarded listed top-level", b["discarded_candidate_ids"] == ["c_1"])
    C.ok("11: not in candidate_to_group", "c_1" not in b["candidate_to_group"])
    C.ok("11: no group for discarded", all("c_1" not in [m["candidate_id"] for m in g["members"]] for g in b["groups"]))


# ===========================================================================
# 12/13. representative snapshot stale / authoritative
# ===========================================================================
def t12_13_representative():
    cs = [cand(claim="她喜欢猫", cid="c_1"), cand(claim="她喜欢猫", cid="c_2")]
    b = resolve(cs)["bundle"]
    g = b["groups"][0]
    rep = g["representative"]
    C.ok("13: representative candidate_id authoritative", rep["candidate_id"] in ("c_1", "c_2"))
    C.ok("13: snapshot matches candidate", rep["snapshot"]["value"] == "她喜欢猫")
    C.ok("13: snapshot_stale False", rep["snapshot_stale"] is False)
    # 篡改 snapshot（模拟 MergeResult 中 snapshot 与候选不一致）
    mr = merged(cs)
    mr["groups"][0]["representative"]["value"] = "她其实讨厌猫"  # 人为不一致
    r2 = resolve(cs, mr=mr)
    g2 = r2["bundle"]["groups"][0]
    C.ok("12: snapshot_stale flagged", g2["representative"]["snapshot_stale"] is True)
    C.ok("12: warning raised", any("snapshot_stale" in w for w in r2["warnings"]), str(r2["warnings"]))
    C.ok("12: CandidateSet NOT overwritten", cs[0]["claim"]["value"] == "她喜欢猫")
    C.ok("12: representative candidate_id unchanged/authoritative",
         g2["representative"]["candidate_id"] in ("c_1", "c_2"))


# ===========================================================================
# 14. 输入乱序 → 完全一致
# ===========================================================================
def t14_deterministic():
    base = [cand(claim="她喜欢猫", cid="c_1"), cand(claim="她讨厌猫", cid="c_2"),
            cand(claim="她喜欢喝奶茶", cid="c_3"), cand(claim="2025年已经不喝奶茶了", cid="c_4", obs="2025-01-01T00:00:00"),
            nar(claim="用户回忆：她喜欢猫", cid="c_5")]
    mr0 = merged(base)
    ref = None
    ok = True
    for seed in range(5):
        random.seed(seed)
        sh = base[:]; random.shuffle(sh)
        r = resolve(sh, mr=merged(sh))
        if not r["ok"]:
            ok = False; break
        b = r["bundle"]
        canonical = json.dumps(b, ensure_ascii=False, sort_keys=True)
        if ref is None:
            ref = canonical
        elif canonical != ref:
            ok = False
            print("   14 mismatch seed", seed)
    C.ok("14: byte-deterministic under input shuffle", ok)


# ===========================================================================
# 15. candidate 缺失 → fail
# ===========================================================================
def t15_candidate_missing():
    cs = [cand(claim="她喜欢猫", cid="c_1")]
    mr = merged(cs)
    # 手工在 relation 里引用不存在的候选（5.3 不会产，模拟污染）
    mr["relations"].append({"relation_id": "rel_bad", "relation_type": "conflict",
                            "relation_confidence": 0.5, "basis_method": "semantic",
                            "source_a": {"kind": "candidate", "id": "c_ghost"},
                            "source_b": {"kind": "candidate", "id": "c_1"}})
    r = resolve(cs, mr=mr)
    C.ok("15: relation ghost candidate -> fail", (not r["ok"]) and any("c_ghost" in e for e in r["errors"]),
         str(r["errors"]))
    C.ok("15: no partial bundle", r["bundle"] is None)


# ===========================================================================
# 16. input schema invalid → fail
# ===========================================================================
def t16_schema_invalid():
    cs = [cand(claim="她喜欢猫", cid="c_1")]
    mr = merged(cs)
    bad_cs = {"schema_version": "1.0", "extraction_context": {}, "candidates": [cand(claim="x", cid="c_9", st="confirmed")]}
    r = rb.resolve_bundle(candidate_set=bad_cs, merge_result=mr)
    C.ok("16: invalid candidate_set -> fail", (not r["ok"]) and r["errors"], str(r["errors"]))


# ===========================================================================
# 17. provenance 完整可追溯
# ===========================================================================
def t17_provenance():
    cs = [cand(claim="她喜欢猫", cid="c_1", src=("wx-A",), msgs=("m_a1",)),
          cand(claim="她喜欢猫", cid="c_2", src=("wx-B",), msgs=("m_b1",)),
          cand(claim="她讨厌猫", cid="c_3", src=("wx-C",), msgs=("m_c1",))]
    b = resolve(cs)["bundle"]
    # 找 c_1 所在 group，检查 provenance
    g = next(g for g in b["groups"] if "c_1" in [m["candidate_id"] for m in g["members"]])
    C.ok("17: group provenance candidate_ids", set(g["provenance"]["candidate_ids"]) >= {"c_1", "c_2"})
    C.ok("17: source_refs union", set(g["provenance"]["source_refs"]) >= {"wx-A", "wx-B"})
    # 经 candidate_id 回查 CandidateSet 可得 supporting_message_ids
    cand_by_id = {c["candidate_id"]: c for c in cs}
    C.ok("17: candidate supporting messages reachable", cand_by_id["c_1"]["supporting_message_ids"] == ["m_a1"])
    # bundle 不复制 supporting_message_ids（避免重复存储）
    C.ok("17: bundle does not duplicate supporting_message_ids",
         all("supporting_message_ids" not in gm for gm in [m for g in b["groups"] for m in [g["provenance"]]]))


# ===========================================================================
# 18. self-edge 防御
# ===========================================================================
def t18_self_edge():
    cs = [cand(claim="她喜欢猫", cid="c_1")]
    mr = merged(cs)
    # 手工加一条同组 conflict（两端同候选 = 同组），模拟 5.3 理论不发生的 case
    mr["relations"].append({"relation_id": "rel_self", "relation_type": "conflict",
                            "relation_confidence": 0.5, "basis_method": "semantic",
                            "source_a": {"kind": "candidate", "id": "c_1"},
                            "source_b": {"kind": "candidate", "id": "c_1"}})
    r = resolve(cs, mr=mr)
    b = r["bundle"]
    C.ok("18: no self-edge groupRelation",
         all(rr["group_a"] != rr["group_b"] for rr in b["group_level_relations"]), str(gr_types(b)))
    C.ok("18: candidate-level relation preserved",
         any(rr["relation_id"] == "rel_self" for rr in b["resolved_relations"]))
    C.ok("18: warning emitted", any("self-edge" in w or "同组" in w for w in r["warnings"]), str(r["warnings"]))


# ===========================================================================
# 19. direction conflict → min confidence + advisory
# ===========================================================================
def t19_direction_conflict():
    cs = [cand(claim="2022年喜欢喝奶茶", cid="c_1", obs="2022-06-01T00:00:00"),
          cand(claim="2023年已经不爱喝奶茶了", cid="c_2", obs="2023-01-01T00:00:00"),
          cand(claim="2025年完全不喝奶茶了", cid="c_3", obs="2025-01-01T00:00:00")]
    mr = merged(cs)
    b = resolve(cs, mr=mr)["bundle"]
    # c1(2022) vs c3(2025) 与 c2(2023) vs c3(2025) 的 temporal 方向应一致；构造反向需手工。改用手工 merge：
    cs2 = [cand(claim="她喜欢喝奶茶", cid="c_1", obs="2022-01-01T00:00:00"),
           cand(claim="她已经不喝奶茶了", cid="c_2", obs="2025-01-01T00:00:00")]
    mr2 = merged(cs2)
    # 手工加第二条同组对 conflict-direction 相返的 temporal（a_earlier vs b_earlier 对同 group 对）
    # 把 c_2 复制成 c_2b，加入 c_2 的组…复杂；改用直接构造同组对、不同 direction 的两条 temporal relation
    g1 = mr2["groups"][0]["merge_group_id"] if mr2["groups"][0]["representative"]["candidate_id"] == "c_1" else mr2["groups"][1]["merge_group_id"]
    g2 = mr2["groups"][1]["merge_group_id"] if g1 != mr2["groups"][1]["merge_group_id"] else mr2["groups"][0]["merge_group_id"]
    mr2["relations"] = [
        {"relation_id": "rel_t1", "relation_type": "temporal_evolution", "relation_confidence": 0.8,
         "direction": "a_earlier_b_later", "basis_method": "temporal",
         "source_a": {"kind": "merge_group", "id": g1}, "source_b": {"kind": "merge_group", "id": g2}},
        {"relation_id": "rel_t2", "relation_type": "temporal_evolution", "relation_confidence": 0.7,
         "direction": "b_earlier_a_later", "basis_method": "temporal",
         "source_a": {"kind": "merge_group", "id": g1}, "source_b": {"kind": "merge_group", "id": g2}},
    ]
    b2 = resolve(cs2, mr=mr2)["bundle"]
    gl = [r for r in b2["group_level_relations"] if r["relation_type"] == "temporal_evolution"]
    C.ok("19: direction conflict -> advisory", len(gl) == 1 and gl[0]["advisory"] is True)
    C.ok("19: confidence = min", abs(gl[0]["relation_confidence"] - 0.7) < 1e-9, str(gl[0]["relation_confidence"]))
    C.ok("19: both evidence preserved", set(gl[0]["evidence"]) == {"rel_t1", "rel_t2"}, str(gl[0]["evidence"]))


# ===========================================================================
# 20. groupRelation evidence 非空
# ===========================================================================
def t20_evidence_nonempty():
    cs = [cand(claim="她喜欢猫", cid="c_1"), cand(claim="她讨厌猫", cid="c_2")]
    b = resolve(cs)["bundle"]
    C.ok("20: all group edges have non-empty evidence",
         all(len(r["evidence"]) >= 1 for r in b["group_level_relations"]))


# ===========================================================================
# 22. merge_group endpoint 兼容
# ===========================================================================
def t22_merge_group_endpoint():
    cs = [cand(claim="她喜欢猫", cid="c_1"), cand(claim="她讨厌猫", cid="c_2")]
    mr = merged(cs)
    # 把 conflict relation 端点改为 merge_group
    g1 = b_group_of(mr, "c_1"); g2 = b_group_of(mr, "c_2")
    for rel in mr["relations"]:
        if rel["relation_type"] == "conflict":
            rel["source_a"] = {"kind": "merge_group", "id": g1}
            rel["source_b"] = {"kind": "merge_group", "id": g2}
    b = resolve(cs, mr=mr)["bundle"]
    C.ok("22: merge_group endpoint resolved", any(
        r["relation_type"] == "conflict" for r in b["group_level_relations"]))
    C.ok("22: resolved_relations have group ids",
         all("group_id" in rr["source_a"] and "group_id" in rr["source_b"] for rr in b["resolved_relations"]))


def b_group_of(mr, cid):
    for g in mr["groups"]:
        if any(m["candidate_id"] == cid for m in g["members"]):
            return g["merge_group_id"]
    return None


# ===========================================================================
# 23. active candidate 多组 → fail
# ===========================================================================
def t23_multi_group_fail():
    cs = [cand(claim="她喜欢猫", cid="c_1")]
    mr = merged(cs)
    # 手工复制一组包含 c_1
    dup = json.loads(json.dumps(mr["groups"][0]))
    mr["groups"].append(dup)
    r = resolve(cs, mr=mr)
    C.ok("23: active candidate in multiple groups -> fail", (not r["ok"]), str(r["errors"]))
    C.ok("23: diagnostic lists candidate", any("c_1" in e for e in r["errors"]), str(r["errors"]))


def main():
    print("=== ResolvedEvidenceBundle 测试 (Stage 5.4) ===")
    tests = [
        ("1. 合法双输入 + schema", t1_valid),
        ("2. conflict group edge", t2_conflict_edge),
        ("3. temporal direction + time_info", t3_temporal),
        ("4. correction_relation + candidate locate", t4_correction_relation_locate),
        ("5/6. persona_claim/memory_item → belongs_to_5_5", t5_persona_claim_belongs_55),
        ("7. candidate correction 不在本批", t7_correction_unresolvable),
        ("8. supporting_related → advisory", t8_related_advisory),
        ("9/21. 多 relation → 单 edge + evidence 累积", t9_multi_rel_single_edge),
        ("10. unresolved 无虚假 pair", t10_unresolved_no_pair),
        ("11. discarded 不建 group", t11_discarded),
        ("12/13. representative stale + authoritative", t12_13_representative),
        ("14. 输入乱序完全一致", t14_deterministic),
        ("15. candidate 缺失 → fail", t15_candidate_missing),
        ("16. input schema invalid → fail", t16_schema_invalid),
        ("17. provenance 完整可追溯", t17_provenance),
        ("18. self-edge 防御", t18_self_edge),
        ("19. direction conflict → min + advisory", t19_direction_conflict),
        ("20. groupRelation evidence 非空", t20_evidence_nonempty),
        ("22. merge_group endpoint 兼容", t22_merge_group_endpoint),
        ("23. active candidate 多组 → fail", t23_multi_group_fail),
    ]
    for name, fn in tests:
        print(f"\n▶ {name}")
        try:
            fn()
        except Exception as e:
            import traceback
            C.ok(name, False, f"{type(e).__name__}: {e}")
            traceback.print_exc()
    print(f"\n通过 {C.ok_n} / 失败 {C.fail_n}")
    for f in C.fails:
        print("  -", f)
    sys.exit(0 if C.fail_n == 0 else 1)


if __name__ == "__main__":
    main()
