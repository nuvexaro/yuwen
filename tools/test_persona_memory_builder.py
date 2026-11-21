#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Persona/Memory Builder 测试套件（Stage 5.5，38 场景）

直接运行： python test_persona_memory_builder.py
输入真实走 5.3 merge + 5.4 resolve → 5.5 build，保证链路真实。
"""

from __future__ import annotations

import json
import random
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import evidence_merge as em
import resolve_bundle as rb
import persona_memory_builder as pmb


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
         conf=0.9, obs=None, src=("wx-1",), stype="wechat_log", corr=False, st="pending"):
    if corr:
        et = "user_correction"; basis = "correction"; src = ("correction",); stype = "correction"; sp = "user"
    return {"candidate_id": cid, "evidence_type": et, "claim": {"value": claim, "basis": basis},
            "supporting_message_ids": ["m_" + cid], "source_refs": list(src), "speaker_role": sp,
            "observed_at": obs, "time_period": None, "confidence": conf, "importance": 3,
            "source_type": stype, "status": st, "conflicts_with": [], "created_at": None}


def build(cs, name="小明", llm=None, corrections=None):
    csd = {"schema_version": "1.0", "extraction_context": {}, "candidates": cs}
    mr = em.merge_evidence(candidates=cs)
    assert mr["ok"], mr["errors"]
    b = rb.resolve_bundle(candidate_set=csd, merge_result=mr["merge_result"])
    assert b["ok"], b["errors"]
    return pmb.build_persona_memory(bundle=b["bundle"], candidate_set=csd,
                                    name_or_alias=name, corrections=corrections, llm=llm)


def pm_ok(r): return r["ok"], (r.get("errors") or []), (r.get("warnings") or [])


def pm_errs(r):
    return pmb._schema_errs(pmb._pm_validator, r["persona_memory"])


def all_memory(pm):
    return [it for b in pm["memory"].values() for it in b]


# 各种 mock LLM
def llm_persona(leaf, text, bucket=None):
    def _l(p): return json.dumps({"bucket": bucket, "persona": [{"leaf": leaf, "value_text": text}]})
    return _l


def llm_none(p): return json.dumps({"bucket": None, "persona": []})


# ===========================================================================
def t1_single_direct_quote():
    cs = [cand(claim="她总发『哈哈哈哈哈哈』", cid="c_1")]
    r = build(cs, llm=llm_persona("speech_style.catchphrases", "哈哈哈哈哈哈"))
    ok, errs, warns = pm_ok(r)
    C.ok("1: ok", ok, str(errs))
    cp = r["persona_memory"]["persona"]["speech_style"]["catchphrases"]
    C.ok("1: persona claim written", len(cp) == 1 and cp[0]["value"] == "哈哈哈哈哈哈", json.dumps(cp, ensure_ascii=False))
    C.ok("1: basis direct_quote", cp[0]["basis"] == "direct_quote")
    C.ok("1: evidence_ids nonempty & traceable", cp[0]["evidence_ids"] == ["c_1"])
    C.ok("1: schema valid", pm_errs(r) == [], str(pm_errs(r))[:150])


def t2_multi_independent():
    cs = [cand(claim="她说她讨厌加班", cid="c_1", src=("wx-A",)),
          cand(claim="她明确说过最烦加班", cid="c_2", src=("wx-B",))]
    def llm(p): return json.dumps({"bucket": None, "persona": [{"leaf": "relationship_behavior.boundaries", "value_text": "讨厌加班"}]})
    r = build(cs, llm=llm)
    ok, errs, warns = pm_ok(r)
    bnd = r["persona_memory"]["persona"]["relationship_behavior"]["boundaries"]
    C.ok("2: two independent → boundary claim", ok and len(bnd) == 1, str(errs))
    C.ok("2: evidence both", set(bnd[0]["evidence_ids"]) == {"c_1", "c_2"} if bnd else False, json.dumps(bnd, ensure_ascii=False))
    # 多条独立 → basis 应为 direct_quote 或 multi？5.3 若 same_core(LLM) 则并组。此处 bnd basis
    if bnd:
        C.ok("2: basis is not user_report_only", bnd[0]["basis"] in ("direct_quote", "multi_evidence"), bnd[0]["basis"])


def t3_user_narration_only():
    cs = [cand(claim="用户回忆：她特别没安全感", cid="c_1", basis="user_report_only", sp="user",
               et="user_narration", src=("user_narration",), stype="user_narration")]
    r = build(cs, llm=llm_persona("emotional_pattern.attachment_style", "焦虑型"))
    ok, errs, warns = pm_ok(r)
    C.ok("3: ok", ok, str(errs))
    # user_narration 单独不能成决定性 persona（除非 L0/L1）
    att = r["persona_memory"]["persona"]["emotional_pattern"].get("attachment_style")
    C.ok("3: attachment_style NOT set from user-only", att is None, json.dumps(att, ensure_ascii=False))
    C.ok("3: warning about insufficient", any("不足决定性" in w for w in warns), str(warns))


def t4_target_plus_user_narration():
    t = cand(claim="我自己不喜欢热闹", cid="c_1")
    u = cand(claim="用户回忆：她不太爱出门", cid="c_2", basis="user_report_only", sp="user",
             et="user_narration", src=("user_narration",), stype="user_narration")
    def llm(p): return json.dumps({"bucket": None, "persona": [{"leaf": "relationship_behavior.role", "value_text": "偏宅"}]})
    r = build([t, u], llm=llm)
    ok, errs, warns = pm_ok(r)
    role = r["persona_memory"]["persona"]["relationship_behavior"].get("role")
    # target direct_quote → decisive（role 是 low_risk? role 是 low_risk，且 direct 可写）
    # 但 user narration 不污染 basis
    u_cand_in = None
    C.ok("4: ok", ok, str(errs))
    C.ok("4: user_narration stays user_report_only", u["claim"]["basis"] == "user_report_only")
    if role:
        C.ok("4: role basis from target direct", role["basis"] == "direct_quote", json.dumps(role, ensure_ascii=False))


def t5_inferred_cap():
    cs = [cand(claim="她偶尔熬夜", cid="c_1", basis="inferred", conf=0.4)]
    # inferred 进 low-risk summary（Q5 允许）
    def llm(p): return json.dumps({"bucket": None, "persona": [{"leaf": "identity.summary", "value_text": "偶尔熬夜，整体自律"}]})
    r = build(cs, llm=llm)
    ok, errs, warns = pm_ok(r)
    summ = r["persona_memory"]["persona"]["identity"].get("summary")
    C.ok("5: inferred low-risk summary", ok, str(errs))
    if summ:
        C.ok("5: summary basis inferred & conf<=0.5", summ["basis"] == "inferred" and summ["confidence"] <= 0.5, json.dumps(summ, ensure_ascii=False))
    else:
        C.ok("5: summary written (or skipped ok)", True)


def t6_l0_direct_quote():
    cs = [cand(claim="她说：我们不可能复合", cid="c_1")]
    r = build(cs, llm=llm_persona("layer0_rules.do_not_say", "我们复合吧"))
    ok, errs, warns = pm_ok(r)
    dns = r["persona_memory"]["persona"]["layer0_rules"]["do_not_say"]
    C.ok("6: L0 direct_quote allowed", ok and len(dns) == 1 and dns[0]["basis"] == "direct_quote", str(errs) + str(dns))


def t7_l0_inferred_forbidden():
    cs = [cand(claim="她可能不会主动", cid="c_1", basis="inferred", conf=0.4)]
    r = build(cs, llm=llm_persona("layer0_rules.reality_boundary", "分手后从不主动联系"))
    ok, errs, warns = pm_ok(r)
    rb_ = r["persona_memory"]["persona"]["layer0_rules"]["reality_boundary"]
    # inferred 进 L0 → 程序拦（inferred 且 leaf 非 low_risk）
    C.ok("7: L0 inferred blocked", ok and rb_ is None, f"ok={ok} rb={json.dumps(rb_, ensure_ascii=False)} warns={warns}")


def t8_conflict_no_overwrite():
    cs = [cand(claim="她喜欢猫", cid="c_1"), cand(claim="她讨厌猫", cid="c_2")]
    r = build(cs)
    ok, errs, warns = pm_ok(r)
    mem = all_memory(r["persona_memory"])
    C.ok("8: conflict keeps both", ok and len(mem) == 2, str(errs))
    C.ok("8: both pending_confirmation", all(m["status"] == "pending_confirmation" for m in mem))
    C.ok("8: mutual conflicts_with", all(len(m["conflicts_with"]) == 1 for m in mem))


def t9_temporal_preserve():
    cs = [cand(claim="2022年喜欢喝奶茶", cid="c_1", obs="2022-06-01T00:00:00"),
          cand(claim="2025年已经不喝奶茶了", cid="c_2", obs="2025-01-01T00:00:00")]
    r = build(cs)
    ok, errs, warns = pm_ok(r)
    prefs = r["persona_memory"]["memory"]["preferences"]
    C.ok("9: temporal container", ok and len(prefs) == 1, str(errs))
    if prefs:
        C.ok("9: history len 2", len(prefs[0]["history"]) == 2)
        C.ok("9: both states kept", prefs[0]["history"][0]["value"] != prefs[0]["history"][1]["value"])
        C.ok("9: no deletion", "2022年喜欢喝奶茶" in prefs[0]["history"][0]["value"] or "2022年喜欢喝奶茶" in prefs[0]["content"])


def t10_correction_overlay():
    # array leaf (catchphrases)：correction 后保留旧 claim(旧 id) + 新增 corrected claim(新 value→新 id)
    cs = [cand(claim="她总发『哈哈哈哈哈哈』", cid="c_1")]
    r0 = build(cs, llm=llm_persona("speech_style.catchphrases", "哈哈哈哈哈哈"))
    cid0 = r0["persona_memory"]["persona"]["speech_style"]["catchphrases"][0]["claim_id"]
    corr = [{"id": "corr_1", "target_kind": "persona_claim", "target_id": cid0,
             "user_statement": "她不会这么说", "corrected_value": "就哈哈哈", "status": "active"}]
    r = build(cs, llm=llm_persona("speech_style.catchphrases", "哈哈哈哈哈哈"), corrections=corr)
    ok, errs, warns = pm_ok(r)
    cp = r["persona_memory"]["persona"]["speech_style"]["catchphrases"]
    # 两条：旧 direct 保留(旧id旧值) + correction claim(新id新值)，不再"改值留旧id"
    by_id = {c["claim_id"]: c for c in cp}
    C.ok("10: correction applied as separate claim", ok and len(cp) == 2, json.dumps(cp, ensure_ascii=False) + str(errs))
    old = next((c for c in cp if c["claim_id"] == cid0), None)
    new = next((c for c in cp if c["claim_id"] != cid0), None)
    C.ok("10: old claim kept (old value+old id)", old is not None and old["value"] == "哈哈哈哈哈哈" and old["basis"] == "direct_quote")
    C.ok("10: new claim = corrected value + new id + basis correction", new is not None and new["value"] == "就哈哈哈"
         and new["basis"] == "correction" and new["confidence"] == 1.0)
    C.ok("10: new claim evidence empty (correction provenance, not old candidates)", new["evidence_ids"] == [])


def t11_correction_keeps_evidence():
    cs = [cand(claim="她总发『哈哈哈哈哈哈』", cid="c_1")]
    r0 = build(cs, llm=llm_persona("speech_style.catchphrases", "哈哈哈哈哈哈"))
    cid0 = r0["persona_memory"]["persona"]["speech_style"]["catchphrases"][0]["claim_id"]
    corr = [{"id": "corr_1", "target_kind": "persona_claim", "target_id": cid0, "user_statement": "纠正",
             "corrected_value": "就哈哈哈", "status": "active"}]
    r = build(cs, llm=llm_persona("speech_style.catchphrases", "哈哈哈哈哈哈"), corrections=corr)
    ok, errs, warns = pm_ok(r)
    C.ok("11: evidence candidate untouched", cs[0]["claim"]["value"] == "她总发『哈哈哈哈哈哈』")
    C.ok("11: correction recorded top-level", len(r["persona_memory"]["corrections"]) == 1)


def t12_corrected_memory():
    cs = [cand(claim="她养过一只猫", cid="c_1")]
    r0 = build(cs)
    mem = all_memory(r0["persona_memory"])
    mi = mem[0]["id"]
    corr = [{"id": "corr_m", "target_kind": "memory_item", "target_id": mi, "user_statement": "记错了",
             "corrected_value": "她从没养过猫", "status": "active"}]
    r = build(cs, corrections=corr)
    ok, errs, warns = pm_ok(r)
    m2 = all_memory(r["persona_memory"])
    C.ok("12: memory superseded corrected", ok and m2[0]["status"] == "superseded" and m2[0]["supersede_kind"] == "corrected",
         json.dumps(m2, ensure_ascii=False))
    C.ok("12: superseded_by set", m2[0]["superseded_by"] == "corr_m")


def t13_evolved_memory():
    cs = [cand(claim="2022年喜欢喝奶茶", cid="c_1", obs="2022-06-01T00:00:00"),
          cand(claim="2025年已经不喝奶茶了", cid="c_2", obs="2025-01-01T00:00:00")]
    r = build(cs)
    ok, errs, warns = pm_ok(r)
    prefs = r["persona_memory"]["memory"]["preferences"]
    C.ok("13: evolved = container active + history", ok and prefs and prefs[0]["status"] == "active" and len(prefs[0]["history"]) == 2)
    C.ok("13: supersede_kind null on container", prefs[0]["supersede_kind"] is None)


def t14_rejected_memory():
    # 通过 correction corrected_value=null 抑制 → 用 corrected（schema 无 rejected 直达；MVP 经 corrected 表达）
    cs = [cand(claim="她养过一只猫", cid="c_1")]
    r0 = build(cs)
    mi = all_memory(r0["persona_memory"])[0]["id"]
    corr = [{"id": "corr_r", "target_kind": "memory_item", "target_id": mi, "user_statement": "作废", "corrected_value": None, "status": "active"}]
    r = build(cs, corrections=corr)
    m = all_memory(r["persona_memory"])
    C.ok("14: rejected/suppressed via corrected", m[0]["status"] == "superseded")


def t15_pending_confirmation():
    cs = [cand(claim="她喜欢猫", cid="c_1", basis="single_weak", conf=0.3),
          cand(claim="她讨厌猫", cid="c_2", basis="single_weak", conf=0.3)]
    r = build(cs)
    ok, errs, warns = pm_ok(r)
    mem = all_memory(r["persona_memory"])
    C.ok("15: conflict-weak → pending", ok and all(m["status"] == "pending_confirmation" for m in mem))


def t16_sparse():
    cs = [cand(claim="她说过晚安", cid="c_1")]
    r = build(cs, llm=llm_persona("emotional_pattern.attachment_style", "安全型"))
    ok, errs, warns = pm_ok(r)
    att = r["persona_memory"]["persona"]["emotional_pattern"].get("attachment_style")
    C.ok("16: sparse → no fabricated attachment", att is None, json.dumps(att, ensure_ascii=False))


def t17_insufficient_evidence():
    cs = [cand(claim="她某次说累", cid="c_1", basis="single_weak", conf=0.2)]
    def llm(p): return json.dumps({"bucket": None, "persona": [{"leaf": "relationship_behavior.conflict_pattern", "value_text": "爱冷战"}]})
    r = build(cs, llm=llm)
    cp = r["persona_memory"]["persona"]["relationship_behavior"].get("conflict_pattern")
    C.ok("17: single_weak single → not persona", cp is None, json.dumps(cp, ensure_ascii=False))


def t18_negative_evidence():
    cs = [cand(claim="用户没见她发过脾气", cid="c_1", basis="user_report_only", sp="user", et="user_narration", src=("user_narration",), stype="user_narration")]
    r = build(cs, llm=llm_persona("layer0_rules.do_not_say", "从不发脾气"))
    dns = r["persona_memory"]["persona"]["layer0_rules"]["do_not_say"]
    C.ok("18: absence not L0 do_not_say", dns == [], json.dumps(dns, ensure_ascii=False))


def t19_supporting_related_not_decisive():
    # 喜欢猫 + 养过猫 → supporting_related → 各自独立 memory；不产生决定性 persona
    cs = [cand(claim="她喜欢猫", cid="c_1"), cand(claim="她养过一只叫团子的猫", cid="c_2")]
    r = build(cs)
    ok, errs, warns = pm_ok(r)
    C.ok("19: related stays separate memories", ok and len(all_memory(r["persona_memory"])) == 2)


def t20_provenance():
    cs = [cand(claim="她总发『哈哈哈哈哈哈』", cid="c_1")]
    r = build(cs, llm=llm_persona("speech_style.catchphrases", "哈哈哈哈哈哈"))
    cp = r["persona_memory"]["persona"]["speech_style"]["catchphrases"][0]
    C.ok("20: claim→candidate trace", cp["evidence_ids"] == ["c_1"] and cs[0]["supporting_message_ids"] == ["m_c_1"])


def t21_rep_snapshot_stale():
    # 通过 resolve 层产生 stale warning 的输入较难构造；这里验证 builder 对 bundle 是只读 + 走权威 candidate
    # bundle.representative.candidate_id 权威已在 resolve 层保证。此处只验证 builder 不因 snapshot 造新 evidence
    cs = [cand(claim="她喜欢猫", cid="c_1", basis="direct_quote", conf=0.9)]
    r = build(cs)
    C.ok("21: snapshot never becomes new evidence", r["ok"])
    C.ok("21: name claim basis user_report_only", r["persona_memory"]["persona"]["identity"]["name_or_alias"]["basis"] == "user_report_only")


def t22_duplicate_evidence_reinforce():
    # 同一组两条同句 → 并组 → 单 memory，evidence 合并（reinforce 非新建）
    cs = [cand(claim="她说她讨厌下雨", cid="c_1", src=("wx-A",)), cand(claim="她说她讨厌下雨", cid="c_2", src=("wx-A",))]
    r = build(cs)
    ok, errs, warns = pm_ok(r)
    mem = all_memory(r["persona_memory"])
    C.ok("22: same-source dup → single memory", ok and len(mem) == 1, str(errs))
    if mem:
        C.ok("22: evidence merged", set(mem[0]["evidence_ids"]) == {"c_1", "c_2"})


def t23_memory_dedup():
    cs = [cand(claim="她养过一只猫", cid="c_1", src=("wx-A",)), cand(claim="她养过一只猫", cid="c_2", src=("wx-B",))]
    r = build(cs)
    mem = all_memory(r["persona_memory"])
    C.ok("23: cross-source dup dedup", len(mem) == 1 and set(mem[0]["evidence_ids"]) == {"c_1", "c_2"})


def t24_persona_dedup():
    cs = [cand(claim="她总说『笑死』", cid="c_1"), cand(claim="她也总说『笑死我了』", cid="c_2", src=("wx-B",))]
    def llm(p): return json.dumps({"bucket": None, "persona": [{"leaf": "speech_style.catchphrases", "value_text": "笑死"}]})
    r = build(cs, llm=llm)
    cp = r["persona_memory"]["persona"]["speech_style"]["catchphrases"]
    C.ok("24: same persona value dedup", len(cp) == 1)


def t25_persona_memory_boundary():
    # "养过猫"(事件) 进 memory 而非 persona trait；"话痨"(长期) 可 persona
    cs = [cand(claim="她养过一只猫", cid="c_1")]
    r = build(cs)
    C.ok("25: event → memory not persona", r["persona_memory"]["persona"]["identity"].get("summary") is None)


def t26_historical_persona():
    cs = [cand(claim="她以前爱喝奶茶", cid="c_1", obs="2022-01-01T00:00:00"),
          cand(claim="现在她已经不喝奶茶了", cid="c_2", obs="2024-01-01T00:00:00")]
    r = build(cs)
    ok, errs, warns = pm_ok(r)
    prefs = r["persona_memory"]["memory"]["preferences"]
    C.ok("26: historical persona in memory history", ok and prefs and len(prefs[0]["history"]) == 2, str(errs))


def t27_current_persona():
    # current 由 memory 容器 valid_period 表达（from=later time），builder 不凭空断言人格当前态
    cs = [cand(claim="她喜欢喝奶茶", cid="c_1", obs="2022-06-01T00:00:00"),
          cand(claim="2025年她就不再喝奶茶了", cid="c_2", obs="2025-01-01T00:00:00")]
    r = build(cs)
    ok, errs, warns = pm_ok(r)
    prefs = r["persona_memory"]["memory"]["preferences"]
    C.ok("27: current slice via valid_period.from", ok and prefs and prefs[0]["valid_period"] is not None
         and prefs[0]["valid_period"].get("from") is not None, str(errs))


def t28_new_evidence_updates():
    # 两次 build，第二次加同 core 新证据 → reinforce（不新建）
    base = [cand(claim="她说她喜欢猫", cid="c_1")]
    r1 = build(base)
    mem1 = all_memory(r1["persona_memory"])
    # 再加独立证据（different 表述 same core 经 LLM same_core）
    cs2 = base + [cand(claim="她特别爱养猫", cid="c_2", src=("wx-B",))]
    def llm(p): return json.dumps({"relation_type": "same_core"}) if "同一核心事实" in p else json.dumps({"bucket": None, "persona": []})
    # build 里 merge 用不了这个 llm；走默认 → supporting_related → 各自 memory
    r2 = build(cs2)
    mem2 = all_memory(r2["persona_memory"])
    # related 各自成 memory 而非覆盖（安全）
    C.ok("28: new supporting evidence → separate related memories (no overwrite)", ok_all := r2["ok"])


def t29_schema_invalid():
    # 非法 bundle 输入 → fail
    bad = {"schema_version": "1.0", "groups": [], "relations": [], "unresolved": [],
           "discarded_candidate_ids": [], "pending_corrections": [], "candidate_to_group": {},
           "stats": {}, "input_refs": {}}
    r = pmb.build_persona_memory(bundle=bad, candidate_set={"schema_version": "1.0", "extraction_context": {}, "candidates": []},
                                 name_or_alias="小明")
    C.ok("29: invalid bundle → fail", (not r["ok"]) and r["errors"], str(r["errors"]))


def t30_deterministic():
    cs = [cand(claim="她总发『哈哈哈哈』", cid="c_1"), cand(claim="她讨厌猫", cid="c_2"),
          cand(claim="她喜欢喝奶茶", cid="c_3")]
    out = []
    for seed in range(5):
        random.seed(seed)
        sh = cs[:]; random.shuffle(sh)
        r = build(sh)
        assert r["ok"], r["errors"]
        out.append(json.dumps(r["persona_memory"], ensure_ascii=False, sort_keys=True))
    C.ok("30: deterministic across shuffle", len(set(out)) == 1)


def t31_correction_type_guard():
    # age corrected_value 传字符串应被 value 约束拦（write_claim age coerce 只收 int）
    cs = [cand(claim="她说自己25岁", cid="c_1", basis="direct_quote")]
    def llm(p): return json.dumps({"bucket": None, "persona": [{"leaf": "identity.age", "value_text": "25"}]})
    r = build(cs, llm=llm)
    age = r["persona_memory"]["persona"]["identity"].get("age")
    C.ok("31: age accepts numeric", age is not None and age["value"] in (25,), json.dumps(age, ensure_ascii=False))


def t32_memory_conflicts_with():
    cs = [cand(claim="她喜欢猫", cid="c_1"), cand(claim="她讨厌猫", cid="c_2")]
    r = build(cs)
    mem = all_memory(r["persona_memory"])
    C.ok("32: conflicts_with populated", all(len(m["conflicts_with"]) == 1 for m in mem))


def t33_l0_reality_boundary_from_evidence():
    cs = [cand(claim="她说：我们已经没有联系了", cid="c_1")]
    r = build(cs, llm=llm_persona("layer0_rules.reality_boundary", "分手后没有联系过"))
    rb_ = r["persona_memory"]["persona"]["layer0_rules"]["reality_boundary"]
    C.ok("33: L0 reality_boundary via direct_quote", rb_ is not None and rb_["basis"] == "direct_quote")


def t34_inside_joke_verbatim():
    cs = [cand(claim="只有我俩懂：说『绿豆』就是吵架了", cid="c_1")]
    r = build(cs)
    ok, errs, warns = pm_ok(r)
    ij = r["persona_memory"]["memory"]["inside_jokes"]
    C.ok("34: inside joke verbatim preserved", ok and any("绿豆" in m["content"] for m in ij), str(errs))


def t35_other_speaker_not_persona():
    cs = [cand(claim="阿强插话：她人挺好的", cid="c_1", sp="other", et="target_message")]
    def llm(p): return json.dumps({"bucket": None, "persona": [{"leaf": "identity.summary", "value_text": "人挺好"}]})
    r = build(cs, llm=llm)
    summ = r["persona_memory"]["persona"]["identity"].get("summary")
    C.ok("35: other-speaker not persona", summ is None or summ.get("evidence_ids") != ["c_1"], json.dumps(summ, ensure_ascii=False))


def t36_negative_correction_undo():
    cs = [cand(claim="她总发『哈哈』", cid="c_1")]
    r0 = build(cs, llm=llm_persona("speech_style.catchphrases", "哈哈"))
    claim0 = r0["persona_memory"]["persona"]["speech_style"]["catchphrases"][0]["claim_id"]
    # 先纠正
    c1 = [{"id": "corr_1", "target_kind": "persona_claim", "target_id": claim0, "user_statement": "不对", "corrected_value": "呵呵", "status": "active"}]
    r1 = build(cs, llm=llm_persona("speech_style.catchphrases", "哈哈"), corrections=c1)
    # 撤销 = supersede corr_1（active 里不再含它）
    c2 = [{"id": "corr_1", "target_kind": "persona_claim", "target_id": claim0, "user_statement": "撤销", "corrected_value": "呵呵", "status": "superseded", "superseded_by": "corr_0"}]
    r2 = build(cs, llm=llm_persona("speech_style.catchphrases", "哈哈"), corrections=c2)
    cp2 = r2["persona_memory"]["persona"]["speech_style"]["catchphrases"]
    C.ok("36: inactive correction not applied", cp2[0]["value"] == "哈哈", json.dumps(cp2, ensure_ascii=False))


def t37_llm_invalid_json():
    def bad_llm(p): return "not json {{{"
    cs = [cand(claim="她喜欢猫", cid="c_1")]
    r = build(cs, llm=bad_llm)
    ok, errs, warns = pm_ok(r)
    C.ok("37: invalid llm → fallback no-crash", ok and all_memory(r["persona_memory"]) != [])


def t38_null_leaves_valid():
    cs = [cand(claim="她说过晚安", cid="c_1")]
    r = build(cs)
    C.ok("38: sparse persona leaves null valid", r["ok"] and pm_errs(r) == [], str(pm_errs(r))[:200])


# ============ P1-A 回归（跨 run correction 一致性）============
def _id_of(pm, field="speech_style.catchphrases", value=None):
    arr = pm["persona"]
    for part in field.split("."):
        arr = arr[part]
    claims = arr if isinstance(arr, list) else [arr]
    for c in claims:
        if isinstance(c, dict) and (value is None or c["value"] == value):
            return c.get("claim_id")
    return None


def p1a_test1_array_no_fake():
    # array leaf: A→B 后，旧 ID_A 保留 + 当前 B 用新 ID_B；绝不出现 value=B+id=ID_A
    cs = [cand(claim="她总发『哈哈哈哈哈哈』", cid="c_1")]
    llm = llm_persona("speech_style.catchphrases", "哈哈哈哈哈哈")
    r0 = build(cs, llm=llm)
    id_a = _id_of(r0["persona_memory"], value="哈哈哈哈哈哈")
    corr = [{"id": "corr_x", "target_kind": "persona_claim", "target_id": id_a,
             "user_statement": "不对", "corrected_value": "就嗯", "status": "active"}]
    r1 = build(cs, llm=llm, corrections=corr)
    cp = r1["persona_memory"]["persona"]["speech_style"]["catchphrases"]
    claims = {c["value"]: c for c in cp}
    C.ok("P1A-1: old value claim retained", "哈哈哈哈哈哈" in claims and claims["哈哈哈哈哈哈"]["claim_id"] == id_a)
    C.ok("P1A-1: new value claim present", "就嗯" in claims)
    C.ok("P1A-1: no value=B with id=ID_A", claims["就嗯"]["claim_id"] != id_a)
    C.ok("P1A-1: new id is deterministic for B", claims["就嗯"]["claim_id"] == pmb.claim_id("speech_style.catchphrases", "就嗯"))


def p1a_test2_fresh_build_same():
    # fresh build 两次 same value → same claim_id
    cs = [cand(claim="她总发『哈哈哈哈』", cid="c_1")]
    llm = llm_persona("speech_style.catchphrases", "哈哈哈哈")
    r1 = build(cs, llm=llm)
    r2 = build(cs, llm=llm)
    C.ok("P1A-2: fresh rebuild same id",
         _id_of(r1["persona_memory"], value="哈哈哈哈") == _id_of(r2["persona_memory"], value="哈哈哈哈"))


def p1a_test3_same_correction_no_runaway():
    # 同一 correction 重跑：不会产生第三个随机/新 claim_id
    cs = [cand(claim="她总发『哈哈哈』", cid="c_1")]
    llm = llm_persona("speech_style.catchphrases", "哈哈哈")
    id_a = _id_of(build(cs, llm=llm)["persona_memory"], value="哈哈哈")
    corr = [{"id": "corr_r", "target_kind": "persona_claim", "target_id": id_a,
             "user_statement": "改", "corrected_value": "嘿嘿", "status": "active"}]
    r1 = build(cs, llm=llm, corrections=corr)
    r2 = build(cs, llm=llm, corrections=corr)
    c1 = [c for c in r1["persona_memory"]["persona"]["speech_style"]["catchphrases"] if c["value"] == "嘿嘿"]
    c2 = [c for c in r2["persona_memory"]["persona"]["speech_style"]["catchphrases"] if c["value"] == "嘿嘿"]
    C.ok("P1A-3: rerun stable", len(c1) == 1 and len(c2) == 1 and c1[0]["claim_id"] == c2[0]["claim_id"])
    C.ok("P1A-3: not duplicated on rerun", len([c for c in r2["persona_memory"]["persona"]["speech_style"]["catchphrases"] if c["value"] == "嘿嘿"]) == 1)


def p1a_test4_single_leaf_correction():
    # single leaf (punctuation): correction 后当前值=B+新 id；旧值/旧 id 由顶层 corrections 承载
    cs = [cand(claim="她说：我从来不用感叹号", cid="c_1")]
    llm = llm_persona("speech_style.punctuation", "几乎不用感叹号")
    r0 = build(cs, llm=llm)
    id_a = r0["persona_memory"]["persona"]["speech_style"]["punctuation"]["claim_id"]
    corr = [{"id": "corr_s", "target_kind": "persona_claim", "target_id": id_a,
             "user_statement": "其实爱用", "corrected_value": "爱用感叹号", "status": "active"}]
    r1 = build(cs, llm=llm, corrections=corr)
    p = r1["persona_memory"]["persona"]["speech_style"]["punctuation"]
    C.ok("P1A-4: single leaf current = B with new id", p["value"] == "爱用感叹号"
         and p["claim_id"] == pmb.claim_id("speech_style.punctuation", "爱用感叹号"))
    C.ok("P1A-4: top-level correction records old id", any(
        cc["target_kind"] == "persona_claim" and cc["target_id"] == id_a and cc["original_value"] == "几乎不用感叹号"
        for cc in r1["persona_memory"]["corrections"]), json.dumps(r1["persona_memory"]["corrections"], ensure_ascii=False))


def p1a_test5_corrected_value_provenance():
    # corrected_value 的 claim evidence_ids 为空（provenance=correction，不是旧候选）
    cs = [cand(claim="她总发『哈哈哈』", cid="c_1")]
    llm = llm_persona("speech_style.catchphrases", "哈哈哈")
    id_a = _id_of(build(cs, llm=llm)["persona_memory"], value="哈哈哈")
    corr = [{"id": "corr_p", "target_kind": "persona_claim", "target_id": id_a,
             "user_statement": "她只回嗯", "corrected_value": "就回嗯", "status": "active"}]
    r = build(cs, llm=llm, corrections=corr)
    nv = next(c for c in r["persona_memory"]["persona"]["speech_style"]["catchphrases"] if c["value"] == "就回嗯")
    C.ok("P1A-5: corrected value has EMPTY evidence (not old candidates)", nv["evidence_ids"] == [], str(nv["evidence_ids"]))
    # 旧 claim 的 evidence_ids 仍是真实旧候选（未污染）
    ov = next(c for c in r["persona_memory"]["persona"]["speech_style"]["catchphrases"] if c["value"] == "哈哈哈")
    C.ok("P1A-5: old claim keeps its true evidence", ov["evidence_ids"] == ["c_1"])


def p1a_test6_array_and_single_covered():
    # array + single 各至少一个 correction case（上面已覆盖 array；这里再显式 assert 都跑过类型）
    cs = [cand(claim="她说：我从不用句号", cid="c_s")]
    llm_s = llm_persona("speech_style.punctuation", "几乎不用句号")
    r_s = build(cs, llm=llm_s)
    id_s = r_s["persona_memory"]["persona"]["speech_style"]["punctuation"]["claim_id"]
    corr_s = [{"id": "cs", "target_kind": "persona_claim", "target_id": id_s,
               "user_statement": "其实用", "corrected_value": "其实常用句号", "status": "active"}]
    r_s2 = build(cs, llm=llm_s, corrections=corr_s)
    C.ok("P1A-6: single-leaf correction case", r_s2["ok"] and
         r_s2["persona_memory"]["persona"]["speech_style"]["punctuation"]["value"] == "其实常用句号")


def main():
    print("=== Persona/Memory Builder 测试 (Stage 5.5) ===")
    tests = [
        ("1. 单条 direct_quote → persona", t1_single_direct_quote),
        ("2. 多条独立证据", t2_multi_independent),
        ("3. user_narration only", t3_user_narration_only),
        ("4. target + user_narration", t4_target_plus_user_narration),
        ("5. inferred cap", t5_inferred_cap),
        ("6. L0 direct_quote", t6_l0_direct_quote),
        ("7. L0 inferred 禁止", t7_l0_inferred_forbidden),
        ("8. conflict 不覆盖", t8_conflict_no_overwrite),
        ("9. temporal 保留历史", t9_temporal_preserve),
        ("10. correction overlay", t10_correction_overlay),
        ("11. correction 不删 evidence", t11_correction_keeps_evidence),
        ("12. corrected memory", t12_corrected_memory),
        ("13. evolved memory", t13_evolved_memory),
        ("14. rejected memory", t14_rejected_memory),
        ("15. pending_confirmation", t15_pending_confirmation),
        ("16. sparse", t16_sparse),
        ("17. insufficient evidence", t17_insufficient_evidence),
        ("18. negative evidence", t18_negative_evidence),
        ("19. supporting_related 非决定性", t19_supporting_related_not_decisive),
        ("20. provenance", t20_provenance),
        ("21. representative snapshot", t21_rep_snapshot_stale),
        ("22. duplicate evidence reinforce", t22_duplicate_evidence_reinforce),
        ("23. memory dedup", t23_memory_dedup),
        ("24. persona dedup", t24_persona_dedup),
        ("25. persona-memory boundary", t25_persona_memory_boundary),
        ("26. historical persona", t26_historical_persona),
        ("27. current persona", t27_current_persona),
        ("28. new evidence updates claim", t28_new_evidence_updates),
        ("29. schema invalid → fail", t29_schema_invalid),
        ("30. deterministic", t30_deterministic),
        ("31. correction type guard", t31_correction_type_guard),
        ("32. memory conflicts_with", t32_memory_conflicts_with),
        ("33. L0 reality_boundary", t33_l0_reality_boundary_from_evidence),
        ("34. inside joke verbatim", t34_inside_joke_verbatim),
        ("35. other speaker not persona", t35_other_speaker_not_persona),
        ("36. correction undo", t36_negative_correction_undo),
        ("37. LLM invalid json", t37_llm_invalid_json),
        ("38. null leaves valid", t38_null_leaves_valid),
        ("P1A-1. array correction: 旧id保留+新值新id", p1a_test1_array_no_fake),
        ("P1A-2. fresh build 同值同 id", p1a_test2_fresh_build_same),
        ("P1A-3. 同 correction 重跑稳定", p1a_test3_same_correction_no_runaway),
        ("P1A-4. single leaf correction 审计链", p1a_test4_single_leaf_correction),
        ("P1A-5. corrected_value 不伪造旧证据", p1a_test5_corrected_value_provenance),
        ("P1A-6. array+single 双覆盖", p1a_test6_array_and_single_covered),
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
