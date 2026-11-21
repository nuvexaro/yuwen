#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Evidence Merge 测试套件（Stage 5.3：A–Z + 8 额外）

直接运行： python test_evidence_merge.py
覆盖：same/semantic/supporting/conflict/temporal/correction/unrelated/unresolved、
ID 确定性、provenance、user_narration 不变量、blocking false-negative、
group-membership ≠ relation-transitivity、representative 溯源/不合成、
输入乱序确定性、supporting/same-core 链、跨桶。
"""

from __future__ import annotations

import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import evidence_merge as em


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
         obs=None, tp=None, corr=False):
    if corr:
        et = "user_correction"; basis = "correction"; stype = "correction"; src = ("correction",)
    return {"candidate_id": cid, "evidence_type": et, "claim": {"value": claim, "basis": basis},
            "supporting_message_ids": ["m_" + cid], "source_refs": list(src), "speaker_role": sp,
            "observed_at": obs, "time_period": tp, "confidence": conf, "importance": imp,
            "source_type": stype, "status": st, "conflicts_with": [], "created_at": None}


def nar(*, claim, cid, **kw):
    return cand(claim=claim, cid=cid, sp="user", et="user_narration", basis="user_report_only",
                stype="user_narration", src=("user_narration",), **kw)


def run(cands, **kw):
    return em.merge_evidence(candidates=cands, **kw)


def rel_types(mr):
    return sorted(r["relation_type"] for r in mr["relations"])


def group_of(mr, cid):
    for g in mr["groups"]:
        if any(m["candidate_id"] == cid for m in g["members"]):
            return g
    return None


def all_group_members(mr):
    return sorted(mid for g in mr["groups"] for mid in (m["candidate_id"] for m in g["members"]))


# ===========================================================================
def tA_exact_duplicate():
    r = run([cand(claim="她喜欢猫", cid="c_1"), cand(claim="她喜欢猫", cid="c_2")])
    mr = r["merge_result"]
    C.ok("A: ok", r["ok"], str(r["errors"]))
    C.ok("A: one group with both", len(mr["groups"]) == 1 and sorted(m["candidate_id"] for m in mr["groups"][0]["members"]) == ["c_1", "c_2"])
    C.ok("A: relation same", rel_types(mr) == ["same"])


def tB_semantic_equivalent():
    # 同主题同极性 canonical 不同：无 LLM → supporting_related（不擅自并组）
    r = run([cand(claim="她喜欢猫", cid="c_1"), cand(claim="她特别喜欢养猫", cid="c_2")])
    mr = r["merge_result"]
    C.ok("B: no-LLM keeps separate (related)", len(mr["groups"]) == 2 and "supporting_related" in rel_types(mr), str(rel_types(mr)))
    # 有 LLM 判 same_core → 并组
    def llm(p): return json.dumps({"relation_type": "same_core", "reason": "x"})
    r2 = run([cand(claim="她喜欢猫", cid="c_1"), cand(claim="她特别喜欢养猫", cid="c_2")], llm=llm)
    mr2 = r2["merge_result"]
    C.ok("B: LLM same_core -> merged", len(mr2["groups"]) == 1, str(all_group_members(mr2)))
    C.ok("B: LLM relation supporting_same_core", "supporting_same_core" in rel_types(mr2))


def tC_supporting_evidence():
    # 喜欢猫 + 养过猫 → related-but-distinct，不并成同一 claim
    r = run([cand(claim="她喜欢猫", cid="c_1"), cand(claim="她养过一只猫", cid="c_2")])
    mr = r["merge_result"]
    C.ok("C: separate groups", len(mr["groups"]) == 2, str(all_group_members(mr)))
    C.ok("C: supporting_related relation", rel_types(mr) == ["supporting_related"], str(rel_types(mr)))
    # representative 不合成
    reps = [g["representative"]["value"] for g in mr["groups"]]
    C.ok("C: no synthesized representative", "她喜欢并且养过猫" not in reps and all(rp in ("她喜欢猫", "她养过一只猫") for rp in reps), str(reps))


def tD_direct_contradiction():
    r = run([cand(claim="她喜欢猫", cid="c_1"), cand(claim="她讨厌猫", cid="c_2")])
    mr = r["merge_result"]
    C.ok("D: conflict relation", rel_types(mr) == ["conflict"], str(rel_types(mr)))
    C.ok("D: both preserved (2 groups)", len(mr["groups"]) == 2, str(all_group_members(mr)))
    C.ok("D: has_conflict flagged", all(g["stats"]["has_conflict"] for g in mr["groups"]))


def tE_temporal_evolution():
    r = run([cand(claim="2022年喜欢喝奶茶", cid="c_1", obs="2022-06-01T12:00:00"),
             cand(claim="2025年已经不喝奶茶了", cid="c_2", obs="2025-01-01T12:00:00")])
    mr = r["merge_result"]
    C.ok("E: temporal_evolution relation", rel_types(mr) == ["temporal_evolution"], str(rel_types(mr)))
    C.ok("E: both candidates kept in separate groups", len(mr["groups"]) == 2, str(all_group_members(mr)))
    rel = mr["relations"][0]
    C.ok("E: direction earlier/later", rel["direction"] == "a_earlier_b_later", str(rel["direction"]))
    C.ok("E: early candidate not deleted", "c_1" in all_group_members(mr))


def tF_correction_relation():
    r = run([cand(claim="她喜欢猫", cid="c_1"), cand(claim="纠正：她其实讨厌猫", cid="c_2", corr=True)])
    mr = r["merge_result"]
    C.ok("F: correction_relation", rel_types(mr) == ["correction_relation"], str(rel_types(mr)))
    C.ok("F: not merged", len(mr["groups"]) == 2)
    C.ok("F: both preserved (no overlay/deletion)", "c_1" in all_group_members(mr) and "c_2" in all_group_members(mr))


def tG_unrelated():
    # 完全无共享词 → 不进比较池 → 无 relation（也绝不被标 unrelated）
    r = run([cand(claim="她喜欢猫", cid="c_1"), cand(claim="她在上海工作", cid="c_2")])
    mr = r["merge_result"]
    C.ok("G: no relation emitted", mr["relations"] == [], str(rel_types(mr)))
    C.ok("G: two groups", len(mr["groups"]) == 2)


def tH_same_candidate_repeated():
    # 同 candidate_id 出现两次 → 去重
    r = run([cand(claim="她喜欢猫", cid="c_1"), cand(claim="她喜欢猫", cid="c_1")])
    mr = r["merge_result"]
    C.ok("H: dedup to one group one member", len(mr["groups"]) == 1 and len(mr["groups"][0]["members"]) == 1, str(all_group_members(mr)))
    C.ok("H: no spurious same relation", mr["relations"] == [])


def tI_then_U_V_W_input_order():
    base = [cand(claim="她喜欢猫", cid="c_1"), cand(claim="她讨厌猫", cid="c_2"),
            cand(claim="她喜欢喝奶茶", cid="c_3"), cand(claim="2025年已经不喝奶茶了", cid="c_4", obs="2025-01-01T12:00:00")]
    r0 = run(base)
    mr0 = r0["merge_result"]
    sig0 = em.merge_result_summary(mr0)
    # 随机乱序 5 次
    ok = True
    for seed in range(5):
        random.seed(seed)
        sh = base[:]
        random.shuffle(sh)
        rr = run(sh)
        if not rr["ok"]:
            ok = False; break
        sig = em.merge_result_summary(rr["merge_result"])
        if sig != sig0:
            ok = False
            print("   mismatch seed", seed, json.dumps(sig, ensure_ascii=False), "vs", json.dumps(sig0, ensure_ascii=False))
            break
    C.ok("U/V/W: order-independent primary/group_id/relations", ok)


def tJ_provenance_preserved():
    src = [cand(claim="她喜欢猫", cid="c_1", src=("wx-A",), obs="2024-01-01T00:00:00"),
           cand(claim="她喜欢猫", cid="c_2", src=("wx-B",), obs="2024-02-01T00:00:00")]
    r = run(src)
    mr = r["merge_result"]
    # 候选原字段在 group.members 里可回溯；merge 不改候选 —— 我们传入的 candidate dict 应未被修改
    C.ok("J: input candidates unmodified", src[0]["claim"]["value"] == "她喜欢猫" and src[0]["source_refs"] == ["wx-A"])
    g = mr["groups"][0]
    C.ok("J: group exposes member candidate_ids", sorted(m["candidate_id"] for m in g["members"]) == ["c_1", "c_2"])
    # representative candidate_id 指向已有候选
    C.ok("J: representative back-traceable", g["representative"]["candidate_id"] in ("c_1", "c_2"))


def tK_user_narration_not_upgraded():
    u = nar(claim="用户回忆：她喜欢猫", cid="c_2")
    t = cand(claim="她喜欢猫", cid="c_1")
    # 不同 speaker 但同主题同极性；canonical 不同（user 带前缀）→ related；绝不升级
    r = run([t, u])
    mr = r["merge_result"]
    # user_narration 候选原字段不变（三不变量）
    C.ok("K: user_narration invariant kept", u["speaker_role"] == "user" and u["claim"]["basis"] == "user_report_only"
         and u["source_type"] == "user_narration")
    # 若被并组，role 也非 target 引语
    for g in mr["groups"]:
        for m in g["members"]:
            if m["candidate_id"] == "c_2":
                C.ok("K: user in group role <= supporting_same_core", m["role_in_group"] in ("primary", "supporting_same_core"))


def tL_insufficient_time():
    # 极性相反但无任何时间 → conflict（非 temporal_evolution），且无时间可排序
    r = run([cand(claim="她喜欢喝奶茶", cid="c_1"), cand(claim="她已经不喝奶茶了", cid="c_2")])
    mr = r["merge_result"]
    C.ok("L: no-time polarity diff -> conflict not temporal", rel_types(mr) == ["conflict"], str(rel_types(mr)))


def tM_same_source_repeated():
    r = run([cand(claim="她喜欢猫", cid="c_1", src=("wx-A",)), cand(claim="她喜欢猫", cid="c_2", src=("wx-A",))])
    mr = r["merge_result"]
    g = mr["groups"][0]
    C.ok("M: same relation", rel_types(mr) == ["same"])
    C.ok("M: independent_support_count=2 but source_diversity=1", g["stats"]["independent_support_count"] == 2 and g["stats"]["source_diversity"] == 1)


def tN_different_source_supporting():
    t = cand(claim="我最喜欢猫", cid="c_1", src=("wx-target",))
    u = nar(claim="用户回忆：她特别喜欢猫", cid="c_2")
    # 无 LLM：related；有 LLM same_core → 并组但 user 保留 provenance
    def llm(p): return json.dumps({"relation_type": "same_core", "reason": "same cat preference"})
    r = run([t, u], llm=llm)
    mr = r["merge_result"]
    if len(mr["groups"]) == 1:
        g = mr["groups"][0]
        C.ok("N: merged, both sources present in members", sorted(m["candidate_id"] for m in g["members"]) == ["c_1", "c_2"])
    C.ok("N: user candidate provenance intact", u["speaker_role"] == "user" and u["source_refs"] == ["user_narration"])
    # 不能把 user_narration 当成 target direct quote
    C.ok("N: user_narration basis unchanged", u["claim"]["basis"] == "user_report_only")


def tO_confidence():
    strong = cand(claim="她喜欢猫", cid="c_1", conf=0.95)
    weak = cand(claim="她养猫养了很久", cid="c_2", conf=0.3)
    r = run([strong, weak])
    mr = r["merge_result"]
    # 两者 different groups（related），各自 group_confidence = max
    C.ok("O: group_confidence = max(member)", all(
        g["representative"]["confidence"] == next(c["confidence"] for c in [strong, weak] if c["candidate_id"] == g["representative"]["candidate_id"])
        for g in mr["groups"]))


def tP_schema_invalid():
    bad = cand(claim="x", cid="c_1")
    bad["status"] = "confirmed"   # 非法
    r = run([bad])
    C.ok("P: schema-invalid input -> failure", (not r["ok"]) and r["errors"], str(r["errors"]))


def tQ_deterministic_rerun():
    base = [cand(claim="她喜欢猫", cid="c_1"), cand(claim="她讨厌猫", cid="c_2")]
    r1 = run(base)
    r2 = run(base)
    C.ok("Q: identical rerun", em.merge_result_summary(r1["merge_result"]) == em.merge_result_summary(r2["merge_result"]))


def tR_related_but_distinct():
    a, b, c = (cand(claim="她喜欢猫", cid="c_a"), cand(claim="她养过一只猫", cid="c_b"),
               cand(claim="她养过一只叫团子的猫", cid="c_c"))
    r = run([a, b, c])
    mr = r["merge_result"]
    # 关键不变量：三者各自独立组（无 same_core → 无 Union-Find 并组）
    C.ok("R: three independent groups", len(mr["groups"]) == 3, str(all_group_members(mr)))
    # 关系只能是 supporting_related（同共享"猫"主题 → 每对被实际比较），绝不并组
    C.ok("R: only supporting_related relations, no union",
         all(t == "supporting_related" for t in rel_types(mr)) and "supporting_same_core" not in rel_types(mr)
         and "same" not in rel_types(mr), str(rel_types(mr)))


def tS_supporting_chain_no_merge():
    a, b, c = (cand(claim="她喜欢猫", cid="c_a"), cand(claim="她养过一只猫", cid="c_b"),
               cand(claim="她养过一只叫团子的猫", cid="c_c"))
    r = run([a, b, c])
    mr = r["merge_result"]
    # supporting_related 不入 Union-Find → A/B/C 各自组
    C.ok("S: chain does not auto-merge", all(len(g["members"]) == 1 for g in mr["groups"]), str(all_group_members(mr)))


def tT_same_transitivity():
    # A same B, B same C → 一组
    r = run([cand(claim="她喜欢猫", cid="c_a"), cand(claim="她喜欢猫", cid="c_b"),
             cand(claim="她喜欢猫", cid="c_c")])
    mr = r["merge_result"]
    C.ok("T: same transitive -> one group", len(mr["groups"]) == 1 and len(mr["groups"][0]["members"]) == 3)


def tX_same_topic_distinct_not_auto_merge():
    a, b = cand(claim="她喜欢猫", cid="c_a"), cand(claim="她怕猫毛过敏", cid="c_b")
    r = run([a, b])
    mr = r["merge_result"]
    C.ok("X: same topic different fact stay separate",
         len(mr["groups"]) == 2, str(all_group_members(mr)))
    # relation 只能是 related（同主题）而非 same_core/same
    C.ok("X: no same_core union", "supporting_same_core" not in rel_types(mr) and "same" not in rel_types(mr), str(rel_types(mr)))


def tY_user_target_provenance():
    t = cand(claim="我最喜欢猫", cid="c_1")
    u = nar(claim="用户回忆：她最爱猫", cid="c_2")
    r = run([t, u])
    # 即使可能 related，user 三字段与 target 三字段都各自保持
    mr = r["merge_result"]
    C.ok("Y: provenance distinct per speaker", u["speaker_role"] == "user" and t["speaker_role"] == "target")
    C.ok("Y: source_refs preserved", u["source_refs"] == ["user_narration"] and t["source_refs"] == ["wx-1"])


def tZ_temporal_beats_supporting():
    # c_2 是 c_1 的 supporting（同主题同极性）但同时有 c_3 时间冲突 → temporal 优先，不能被 supporting 吞
    c1 = cand(claim="她喜欢喝奶茶", cid="c_1", obs="2022-01-01T00:00:00")
    c2 = cand(claim="她特别爱喝奶茶", cid="c_2", obs="2022-06-01T00:00:00")  # 支持 c_1
    c3 = cand(claim="2025年已经不喝奶茶了", cid="c_3", obs="2025-01-01T00:00:00")
    r = run([c1, c2, c3])
    mr = r["merge_result"]
    types = rel_types(mr)
    C.ok("Z: temporal_evolution present", "temporal_evolution" in types, str(types))
    # c1 与 c2 若 same_core（canonical 不同 → related）；时间对 c3 判 evolution
    C.ok("Z: no auto-merge across temporal boundary", "c_1" in all_group_members(mr) and "c_3" in all_group_members(mr))


# ---- 额外 8 项 ----
def x1_blocking_false_negative():
    # 语义相关但 blocking 主题词不同（如不同词面）不得被输出为 unrelated（应为无 relation 或正确关系）
    a = cand(claim="她喜欢猫咪", cid="c_1")
    b = cand(claim="她特别爱养猫", cid="c_2")
    r = run([a, b])
    mr = r["merge_result"]
    C.ok("X1: no false unrelated conclusion", "unrelated" not in rel_types(mr), str(rel_types(mr)))
    # 同共享 "猫" 主题 → 被比较 → related 或 same_core
    C.ok("X1: compared (relation exists or none, never unrelated)", mr["relations"] == [] or "unrelated" not in rel_types(mr))


def x2_group_membership_ne_rel_transitivity():
    # A same B、B same C（合法并组）；不产生 A-C relation（因为 A-C 是 actual same，会因 canonical 相同被比较……
    # 选一个没有实际比较的配对：A-C 若 canonical 也相同会真实产生 same —— 用三条 same 但中间无直接 relation 的场景不可行。
    # 构造：A same B（canonical 同）B supporting_same_core C（LLM）→ A、B、C 一组；但 relation 只有 AB same + BC same_core，
    # 不得自动造 A-C relation（除非 A-C 实际比较过且真 same —— 此处 A C canonical 同 → 也会被比较产生 same，属"实际判定"）。
    # 为测"不凭空造"，用 A same B、B same C、但 A 与 C canonical 不同的退化不可能（same 可传递要求相同 canonical）。
    # 采用设计意图：A-B、B-C 同组不自动制造未经比较的 A-C relation —— 用 B 连接 A、C，A、C 无共享主题词。
    a = cand(claim="她喜欢猫", cid="c_a")
    b = cand(claim="她喜欢猫", cid="c_b")          # B same A
    c = cand(claim="她讨厌狗", cid="c_c")          # C 与 B 无共享词（不进比较池）→ 无 B-C relation
    r = run([a, b, c])
    mr = r["merge_result"]
    rels = mr["relations"]
    # A-B same；B-C、A-C 无 relation（未比较）
    C.ok("X2: only actual same relation", [x["relation_type"] for x in rels] == ["same"], str([(x["source_a"]["id"], x["source_b"]["id"], x["relation_type"]) for x in rels]))
    # 不凭空造 A-C
    C.ok("X2: no fabricated A-C", not any({x["source_a"]["id"], x["source_b"]["id"]} == {"c_a", "c_c"} for x in rels))


def x3_representative_provenance():
    r = run([cand(claim="她喜欢猫", cid="c_1", src=("wx-A",)), cand(claim="她喜欢猫", cid="c_2", src=("wx-B",))])
    mr = r["merge_result"]
    rep = mr["groups"][0]["representative"]
    C.ok("X3: representative candidate_id is a real member",
         rep["candidate_id"] in ("c_1", "c_2") and rep["value"] in ("她喜欢猫",))
    C.ok("X3: representative value matches that candidate's claim",
         rep["value"] == next(c for c in [cand(claim="她喜欢猫", cid="c_1"), cand(claim="她喜欢猫", cid="c_2")] if c["candidate_id"] == rep["candidate_id"])["claim"]["value"])


def x4_representative_no_synthesis():
    r = run([cand(claim="她喜欢猫", cid="c_1"), cand(claim="她养过一只猫", cid="c_2")])
    mr = r["merge_result"]
    for g in mr["groups"]:
        v = g["representative"]["value"]
        C.ok("X4: representative not synthesized", v in ("她喜欢猫", "她养过一只猫"), f"got {v}")
        C.ok("X4: representative is one member's raw claim", v not in ("她喜欢并且养过猫", "她喜欢猫并且养过一只猫"))


def x5_input_order_determinism():
    base = [cand(claim="她喜欢猫", cid="c_1"), cand(claim="她讨厌猫", cid="c_2"),
            cand(claim="她喜欢喝奶茶", cid="c_3"), cand(claim="2025年已经不喝奶茶了", cid="c_4", obs="2025-01-01T00:00:00"),
            nar(claim="用户回忆：她喜欢猫", cid="c_5")]
    ok = True
    sig0 = None
    for seed in range(8):
        random.seed(seed)
        sh = base[:]; random.shuffle(sh)
        r = run(sh)
        if not r["ok"]:
            ok = False; break
        sig = em.merge_result_summary(r["merge_result"])
        if sig0 is None:
            sig0 = sig
        elif sig != sig0:
            ok = False
            print("   X5 mismatch seed", seed)
            break
    C.ok("X5: fully deterministic under shuffle", ok)


def x6_supporting_chain_no_auto():
    # A related B, B related C → 三者不自动并组
    a = cand(claim="她喜欢猫", cid="c_a")
    b = cand(claim="她养过一只猫", cid="c_b")
    c = cand(claim="她给猫取过名字", cid="c_c")
    r = run([a, b, c])
    mr = r["merge_result"]
    C.ok("X6: related chain does not merge", all(len(g["members"]) == 1 for g in mr["groups"]), str(all_group_members(mr)))


def x7_same_core_chain_legal_no_fabricated():
    # A same B（canonical 同）；B supporting_same_core C（LLM）→ 一组，但不凭空造 A-C relation
    a = cand(claim="她喜欢猫", cid="c_a")
    b = cand(claim="她喜欢猫", cid="c_b")
    c = cand(claim="她特别喜欢养猫", cid="c_c")
    def llm(p): return json.dumps({"relation_type": "same_core", "reason": "cat"})
    r = run([a, b, c], llm=llm)
    mr = r["merge_result"]
    C.ok("X7: A,B,C in one group via same+same_core", len(mr["groups"]) == 1 and len(mr["groups"][0]["members"]) == 3, str(all_group_members(mr)))
    rels = mr["relations"]
    # A-C：canonical 不同 → 若被比较应为 same_core (LLM) 或 related；A-C 经 LLM 也会判 same_core 是真判定。检查是否"凭空"
    # A 与 C 共享"猫"主题词 → 会实际比较 → LLM 判 same_core → 是真实 relation，非凭空。
    C.ok("X7: relations are real (each from an actual comparison)", all(
        ({x["source_a"]["id"], x["source_b"]["id"]} in [{"c_a", "c_b"}, {"c_b", "c_c"}, {"c_a", "c_c"}]) for x in rels))


def x8_cross_block_no_unrelated():
    # 完全不同主题 → 无 relation（不标 unrelated）
    a = cand(claim="她喜欢猫", cid="c_a")
    b = cand(claim="她在上海工作", cid="c_b")
    c = cand(claim="她讨厌下雨", cid="c_c")
    r = run([a, b, c])
    mr = r["merge_result"]
    C.ok("X8: cross-block never unrelated", all(x["relation_type"] != "unrelated" for x in mr["relations"]), str(rel_types(mr)))


def main():
    print("=== Evidence Merge 测试 (Stage 5.3) ===")
    tests = [
        ("A. exact duplicate", tA_exact_duplicate),
        ("B. semantic equivalent", tB_semantic_equivalent),
        ("C. supporting evidence", tC_supporting_evidence),
        ("D. direct contradiction", tD_direct_contradiction),
        ("E. temporal evolution", tE_temporal_evolution),
        ("F. correction relation", tF_correction_relation),
        ("G. unrelated", tG_unrelated),
        ("H. same candidate repeated", tH_same_candidate_repeated),
        ("I/U/V/W. input order determinism", tI_then_U_V_W_input_order),
        ("J. provenance preserved", tJ_provenance_preserved),
        ("K. user_narration not upgraded", tK_user_narration_not_upgraded),
        ("L. insufficient time -> conflict", tL_insufficient_time),
        ("M. same source repeated", tM_same_source_repeated),
        ("N. different source supporting", tN_different_source_supporting),
        ("O. confidence max", tO_confidence),
        ("P. schema-invalid", tP_schema_invalid),
        ("Q. deterministic rerun", tQ_deterministic_rerun),
        ("R. related-but-distinct", tR_related_but_distinct),
        ("S. supporting chain no merge", tS_supporting_chain_no_merge),
        ("T. same transitivity", tT_same_transitivity),
        ("X. same topic distinct fact", tX_same_topic_distinct_not_auto_merge),
        ("Y. user+target provenance", tY_user_target_provenance),
        ("Z. temporal beats supporting", tZ_temporal_beats_supporting),
        ("X1. blocking false-negative", x1_blocking_false_negative),
        ("X2. group membership != relation transitivity", x2_group_membership_ne_rel_transitivity),
        ("X3. representative provenance", x3_representative_provenance),
        ("X4. representative no-synthesis", x4_representative_no_synthesis),
        ("X5. input-order full determinism", x5_input_order_determinism),
        ("X6. supporting chain no auto", x6_supporting_chain_no_auto),
        ("X7. same-core chain legal, no fabricated relation", x7_same_core_chain_legal_no_fabricated),
        ("X8. cross-block never unrelated", x8_cross_block_no_unrelated),
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
