#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Persona Runtime 测试（Stage 5.7）。

覆盖：retrieval、persona 优先级、reality boundary、session、proposal、
correction、gateway、context、determinism。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import shutil
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.dirname(HERE)
TOOLS = os.path.join(os.path.dirname(RUNTIME), "tools")
for p in (RUNTIME, TOOLS):
    if p not in sys.path:
        sys.path.insert(0, p)

import memory_retrieval as mr  # noqa: E402
import reality_boundary as rb_  # noqa: E402
import context_assembly as ca  # noqa: E402
import persona_constraints as pc  # noqa: E402
import llm_gateway as gw  # noqa: E402
import correction_runtime as cr  # noqa: E402
import memory_proposal as mp  # noqa: E402
import persona_runtime as pr  # noqa: E402
from persona_runtime import PersonaRuntime  # noqa: E402
from mock_responders import simple_responder  # noqa: E402
import session_store as ss  # noqa: E402


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


def claim(field, value, basis="direct_quote", ev=("c_1",)):
    try:
        import persona_memory_builder as pmb
        cid = pmb.claim_id(field, value)
    except Exception:
        cid = "pc_" + value[:8]
    return {"claim_id": cid, "value": value, "evidence_ids": list(ev),
            "confidence": 0.9, "basis": basis}


def sample_pm():
    return {
        "schema_version": "1.2", "revision": 1,
        "persona": {
            "layer0_rules": {
                "do_not_say": [claim("layer0_rules.do_not_say", "别说我们还能复合")],
                "specific_edges": [], "reality_boundary": None},
            "identity": {"name_or_alias": claim("identity.name_or_alias", "小明", "user_report_only"),
                         "relationship": {}},
            "speech_style": {"catchphrases": [claim("speech_style.catchphrases", "哈哈哈哈")],
                             "examples": [], "punctuation": claim("speech_style.punctuation", "几乎不用标点")},
            "emotional_pattern": {"triggers": {"sensitive_topics": [claim("_st", "别问我和谁出去")]}},
            "relationship_behavior": {},
        },
        "memory": {
            "preferences": [{
                "id": "mi_2022milk", "content": "她以前喜欢喝奶茶", "status": "superseded",
                "supersede_kind": "evolved", "superseded_by": "mi_now",
                "history": [{"value": "喜欢喝奶茶", "valid_from": None, "valid_to": None, "evidence_ids": ["c_1"]},
                            {"value": "现在不喝奶茶了", "valid_from": None, "valid_to": None, "evidence_ids": ["c_2"]}],
                "valid_period": {"from": {"value": "2025", "precision": "year"}, "to": None}}],
            "timeline": [],
            "shared_experiences": [{"id": "mi_shanghai", "content": "2022年我们一起去过上海", "status": "active",
                                    "event_time": "2022-06-01", "evidence_ids": ["c_3"]}],
            "conflicts": [{"id": "mi_cat", "content": "她喜欢猫", "status": "pending_confirmation",
                           "conflicts_with": ["mi_dog"]},
                          {"id": "mi_dog", "content": "她讨厌猫", "status": "pending_confirmation",
                           "conflicts_with": ["mi_cat"]}],
            "happy_memories": [], "breakup": [], "inside_jokes": [],
            "core_facts": [{"id": "mi_city", "content": "她住在上海", "status": "active"}],
            "daily_patterns": [],
        },
        "corrections": [],
    }


def make_runtime(pm=None, responder=None, budget=2000):
    g = gw.LLMGateway(adapter=responder or simple_responder, model="mock")
    return PersonaRuntime(persona_memory=pm or sample_pm(), gateway=g, context_budget=budget)


# ============ Retrieval ============
def t_retrieval():
    pm = sample_pm()
    # keyword hit 上海
    r = mr.retrieve(pm, {}, "我们是不是去过上海", k=5)
    ids = [x["memory"]["id"] for x in r["items"]]
    C.ok("retrieval: keyword hit 上海", "mi_shanghai" in ids, str(ids))
    # 无命中
    r2 = mr.retrieve(pm, {}, "今天晚饭吃什么", k=5)
    C.ok("retrieval: no hit → empty", r2["items"] == [], str(r2["items"]))
    # superseded 当前值不作为当前事实（mi_2022milk superseded → 不进 current）
    r3 = mr.retrieve(pm, {}, "奶茶", k=5)
    active_ids = [x["memory"]["id"] for x in r3["items"]]
    C.ok("retrieval: superseded not recalled as current", "mi_2022milk" not in active_ids, str(active_ids))
    # 冲突对：召回猫 → 带出狗
    r4 = mr.retrieve(pm, {}, "她喜欢猫吗", k=5)
    hit = next((x for x in r4["items"] if x["memory"]["id"] == "mi_cat"), None)
    C.ok("retrieval: conflict sibling surfaced", hit is not None and hit["conflict_sibling_id"] == "mi_dog")


def t_retrieval_threshold():
    pm = sample_pm()
    # 无关词低于阈值 → 不召回
    r = mr.retrieve(pm, {}, "飞机引擎怎么修", k=5, threshold=0.3)
    C.ok("retrieval: irrelevant below threshold", r["items"] == [])


def t_g3_lifecycle_filtering():
    """G3-4：rejected / superseded 不作为当前事实召回（主候选 + conflict sibling 两条路径）。

    pending_confirmation **保留**召回（本仓库中它是「冲突对一方、待裁决」，
    见 persona_memory_builder 冲突组 → pending），既有 conflict sibling 机制不受影响。
    """
    pm = sample_pm()
    pm["memory"]["preferences"] = [
        {"id": "mi_rej", "content": "她喜欢奶茶", "status": "rejected", "conflicts_with": []},
        {"id": "mi_sup", "content": "她喜欢奶茶", "status": "superseded", "conflicts_with": []},
        {"id": "mi_act", "content": "她喜欢奶茶", "status": "active", "conflicts_with": []},
    ]
    r = mr.retrieve(pm, {}, "她喜欢奶茶", k=5)
    ids = [x["memory"]["id"] for x in r["items"]]
    C.ok("G3-4: rejected 不被召回", "mi_rej" not in ids, str(ids))
    C.ok("G3-4: superseded 不被召回", "mi_sup" not in ids, str(ids))
    C.ok("G3-4: active 正常召回", "mi_act" in ids, str(ids))

    # conflict sibling 路径：active 项的对手是 rejected → 不把 rejected 带出
    pm2 = sample_pm()
    pm2["memory"]["core_facts"] = [{"id": "mi_x", "content": "她喜欢猫",
                                    "status": "active", "conflicts_with": ["mi_rej"]}]
    pm2["memory"]["conflicts"] = [{"id": "mi_rej", "content": "她讨厌猫",
                                   "status": "rejected", "conflicts_with": ["mi_x"]}]
    r2 = mr.retrieve(pm2, {}, "她喜欢猫", k=5)
    hit = next((x for x in r2["items"] if x["memory"]["id"] == "mi_x"), None)
    C.ok("G3-4: rejected 不被作为 conflict sibling 带出",
         hit is not None and hit["conflict_sibling_id"] is None and "mi_rej" not in r2["used_ids"])

    # 方案 A 回归：pending_confirmation 仍可召回并带出 sibling（既有 conflict-safety 属性）
    pm3 = sample_pm()
    r3 = mr.retrieve(pm3, {}, "她喜欢猫", k=5)
    cat = next((x for x in r3["items"] if x["memory"]["id"] == "mi_cat"), None)
    C.ok("G3-4: pending_confirmation 保留召回（方案 A）+ sibling 仍带出",
         cat is not None and cat["conflict_sibling_id"] == "mi_dog")


def t_g3_default_scorer_unchanged():
    """G3-4：default_scorer() 的 scoring 行为零改动（只做 selection filtering）。"""
    pm = sample_pm()
    act = {"id": "mi_z", "content": "她喜欢猫", "status": "active"}
    sup = {"id": "mi_y", "content": "她喜欢猫", "status": "superseded"}
    rej = {"id": "mi_w", "content": "她喜欢猫", "status": "rejected"}
    # superseded 仍返回 0.0（原有行为）
    C.ok("G3-4: default_scorer(superseded) == 0.0",
         mr.default_scorer("她喜欢猫", sup) == 0.0)
    # 打分算法本身不按新增状态短路：rejected 的分数与 active 同输入一致
    C.ok("G3-4: default_scorer 不因 rejected 短路（scoring 未改）",
         mr.default_scorer("她喜欢猫", rej) == mr.default_scorer("她喜欢猫", act),
         f"{mr.default_scorer('她喜欢猫', rej)} vs {mr.default_scorer('她喜欢猫', act)}")
    # 集合常量语义
    C.ok("G3-4: _NON_CURRENT_STATUSES == {superseded, rejected}",
         mr._NON_CURRENT_STATUSES == frozenset({"superseded", "rejected"}),
         str(mr._NON_CURRENT_STATUSES))


def t_retrieval_evolved_history():
    # evolved 历史可按过去召回：直接测 superseded 容器不 active（上面已证），
    # 历史段召回由上层决定；此处确认 active 容器 valid_period 未来开始不当前召回
    pm = sample_pm()
    pm["memory"]["preferences"][0]["status"] = "active"  # 改成 active + valid_period from 2025
    r = mr.retrieve(pm, {}, "奶茶", k=5, now=datetime(2024, 1, 1))
    ids = [x["memory"]["id"] for x in r["items"]]
    C.ok("retrieval: future valid_period not recalled now(2024)", "mi_2022milk" not in ids, str(ids))


# ============ Persona 优先级 ============
def t_persona_layers():
    pm = sample_pm()
    layers = pc.collect_layers(pm)
    C.ok("persona: L0 has do_not_say", any("复合" in c.get("value", "") for c in layers["L0"]))
    C.ok("persona: L1 has name", any(c.get("value") == "小明" for c in layers["L1"]))
    C.ok("persona: L2 has catchphrase", any("哈哈" in c.get("value", "") for c in layers["L2"]))
    # sensitive 在 L3 并保留
    blk = pc.render_system_block(pm, "小明")
    C.ok("persona: guardrail 非空含护栏", "不是 AI" in blk["guardrail"] or "不突然变得完美" in blk["guardrail"])
    C.ok("persona: L0 block rendered", "复合" in blk["L0"] or "别说" in blk["L0"] or blk["L0"] != "")


def t_sensitive_preserved():
    # sensitive topic 在 L3 block 中出现（不可被 style 覆盖掉 → 它属于 L3 triggers 保留）
    pm = sample_pm()
    blk = pc.render_system_block(pm, "小明")
    C.ok("persona: sensitive topic present in L3", "别问我和谁出去" in blk["L3"], blk["L3"])


# ============ Reality Boundary ============
def t_reality_2022_vs_last_year():
    pm = sample_pm()
    fl = rb_.check_reality(pm, "我们去年去上海了吗？", now=datetime(2026, 9, 1))
    C.ok("reality: 去年(2025) vs 记忆2022 → conflict", fl["reality_conflict"] is True, str(fl))
    C.ok("reality: category question", fl["user_category"] == "question")


def t_reality_question_not_assertion():
    pm = sample_pm()
    C.ok("reality: '吗？' → question", rb_.classify_user_message("我们去年去上海了吗？") == "question")
    C.ok("reality: 陈述 → assertion", rb_.classify_user_message("我明天要去北京") == "assertion")
    C.ok("reality: 可能/大概 → guess", rb_.classify_user_message("她可能不喜欢猫") == "guess")
    C.ok("reality: 不是 → correction", rb_.classify_user_message("不是，你记错了") == "correction")


def t_reality_missing_memory():
    pm = sample_pm()  # 无 2024/2025 事件
    fl = rb_.check_reality(pm, "我们去年去了巴黎", now=datetime(2026, 9, 1))
    C.ok("reality: 去年巴黎 memory无 → 不确定处理（conflict）",
         fl["reality_conflict"] is True and "不确定" in fl.get("note", ""))


def t_reality_conflict_memory():
    pm = sample_pm()
    # 猫 与 讨厌猫 冲突 memory 并存 → runtime 不选边：召回一方即带出冲突对手
    r = mr.retrieve(pm, {}, "她喜欢猫", k=5)
    cat = next((x for x in r["items"] if x["memory"]["id"] == "mi_cat"), None)
    C.ok("reality: conflict sibling surfaced", cat is not None and cat["conflict_sibling_id"] == "mi_dog")
    # 两者都独立相关时也都会在 used（去重后）
    C.ok("reality: conflict not collapsed silently", cat is not None)


def t_reality_old_as_current_postfilter():
    rt = make_runtime()
    r = rt.respond("我们去年去上海了吗？", session_id="r1")
    C.ok("reality-runtime: response not confirming 去年", "去年" not in r["assistant_response"]
         or "不确定" in r["assistant_response"], r["assistant_response"])
    C.ok("reality-runtime: conflict flagged", r["reality_flags"]["reality_conflict"] is True)


# ============ Session ============
def t_session_turns():
    store = ss.SessionStore()
    rt = make_runtime()
    rt.store = store
    r1 = rt.respond("在干嘛", session_id="sx")
    r2 = rt.respond("吃了没", session_id="sx")
    s = store.get("sx")
    C.ok("session: turn_count 2", s is not None and s.turn_count == 2)
    C.ok("session: history has 4 entries (2 rounds)", len(s.history) == 4)
    C.ok("session: recent returns last", len(s.recent(2)) == 2)


def t_session_persistence():
    d = tempfile.mkdtemp()
    store = ss.SessionStore(dir=d)
    rt = make_runtime(); rt.store = store
    rt.respond("你好", session_id="sp")
    # 重开一个 store 从文件加载
    store2 = ss.SessionStore(dir=d)
    s2 = store2.get("sp")
    C.ok("session: file-backed persists turn", s2 is not None and s2.turn_count == 1)
    shutil.rmtree(d)


# ============ Proposal ============
def t_proposal_user_fact():
    p = mp.build_proposal("我最近跳槽去字节了", source_session="s", category="assertion")
    C.ok("proposal: user fact → proposal", p is not None and p["status"] == "pending")
    p2 = mp.build_proposal("我们去年去上海了吗", source_session="s", category="question")
    C.ok("proposal: question not proposal", p2 is None)
    p3 = mp.build_proposal("我今天好累", source_session="s", category="assertion")
    C.ok("proposal: 即时情绪句不长期化", p3 is None)


def t_proposal_llm_not_direct():
    # LLM 台词绝不经 proposal 通道直接进 memory；proposal 只由用户陈述产生
    pm = sample_pm()
    g = gw.LLMGateway(adapter=lambda p, **k: "我记得你以前说过……（这是人格台词）", model="m")
    rt = PersonaRuntime(persona_memory=pm, gateway=g)
    # 用户问（非新事实）→ 无 proposal
    r = rt.respond("你觉得我们以前怎么认识的？", session_id="pn")
    C.ok("proposal: question → no proposal", r["memory_proposals"] == [], str(r["memory_proposals"]))
    # persona_memory 未被 runtime 修改（LLM 台词没进去）
    C.ok("proposal: persona_memory unchanged", all(len(v) == len(pm["memory"][k]) for k, v in pm["memory"].items()))


# ============ Correction ============
def t_correction_overlay():
    # Stage 5.9-B (F5-b re-baseline)：第三人称“她”+ 属性/性格纠正 → target memory 域，
    # 不再命中 persona.speech_style.catchphrases[0]。
    pm = sample_pm()
    # 断言行为契约而非内部实现：先记录 persona 原 bytes
    import copy
    pm_snapshot = copy.deepcopy(pm)
    rt = make_runtime(pm)
    r = rt.respond("不对，她其实不会那么说话", session_id="cr")
    cc = r.get("correction_result")
    C.ok("correction: detected", cc is not None and cc.get("detected") is True)
    if cc:
        # 她属性纠正 → memory 域（core_facts 新 overlay），target_domain=memory
        C.ok("correction: target domain = memory (not catchphrase)",
             cc.get("target_domain") == "memory", json.dumps(cc, ensure_ascii=False))
        # 绝不命中 persona 自己的口头禅 catchphrase
        catch_cid = pm["persona"]["speech_style"]["catchphrases"][0]["claim_id"]
        C.ok("correction: NOT targeting self catchphrase", cc.get("old_claim_id") != catch_cid)
        # memory 域 overlay → 确定性 mi_ id
        C.ok("correction: memory-domain overlay id (mi_)",
             cc.get("new_claim_id") and cc["new_claim_id"].startswith("mi_"), cc.get("new_claim_id"))
        # persona_memory bytes 不变（只写 session overlay）
        C.ok("correction: persona_memory bytes unchanged",
             json.dumps(pm, ensure_ascii=False, sort_keys=True) == json.dumps(pm_snapshot, ensure_ascii=False, sort_keys=True))
        # 重跑同 correction → 同 new claim id（确定性）
        r2 = rt.respond("不对，她其实不会那么说话", session_id="cr2")
        cc2 = r2.get("correction_result")
        C.ok("correction: rerun stable new id", cc2 and cc2.get("new_claim_id") == cc.get("new_claim_id"))
    # 会话内 overlay 实际写入 session（persistable）
    s = rt.store.get("cr")
    C.ok("correction: session overlay written", s is not None and len(s.persona_overlay) >= 1)


def t_correction_missing_target():
    # persona 无 claim 可纠 → 不崩，记录
    pm = sample_pm()
    pm["persona"]["speech_style"]["punctuation"] = None
    rt = make_runtime(pm)
    r = rt.respond("不对，不是那样", session_id="cm")
    C.ok("correction: no-target handled (no crash)", "assistant_response" in r)
    cc = r.get("correction_result")
    if cc:
        C.ok("correction: no-target noted", cc.get("applied_overlay") in (False,) or "note" in cc)


# ============ Gateway ============
def t_gateway_mock():
    g = gw.LLMGateway(adapter=simple_responder, model="mock")
    out = g.chat([gw.ChatMessage("user", "hi")])
    C.ok("gateway: mock returns", isinstance(out, str) and out)
    C.ok("gateway: usage tracked", g.metadata["usage"]["calls"] >= 1)


def t_gateway_timeout_retry():
    calls = {"n": 0}

    def flaky(prompt, **k):
        calls["n"] += 1
        if calls["n"] < 3:
            raise TimeoutError("timeout")
        return "ok-after-retries"
    g = gw.LLMGateway(adapter=flaky, retry=2)
    out = g.chat([gw.ChatMessage("user", "x")])
    C.ok("gateway: retry succeeds", out == "ok-after-retries" and calls["n"] == 3)


def t_gateway_fallback_on_gateway_error():
    def always_fail(prompt, **k):
        raise TimeoutError("always")
    g = gw.LLMGateway(adapter=always_fail, retry=0)
    pm = sample_pm()
    rt = PersonaRuntime(persona_memory=pm, gateway=g)
    r = rt.respond("在干嘛", session_id="gf")
    C.ok("gateway: runtime falls back (no crash, neutral)", isinstance(r["assistant_response"], str)
         and r["assistant_response"] != "")


# ============ Context ============
def t_context_budget_l0_never_dropped():
    pm = sample_pm()
    # 极小预算 → L0/reality/user 仍在；抛错只在比最小还小时
    small = 300
    try:
        ctx = ca.assemble(pm, "小明", "在干嘛", budget=small)
        C.ok("context: small budget ok", "规则" in ctx["system_text"])
        C.ok("context: user message in user_text", ctx["user_text"] == "在干嘛")
    except ca.BudgetExceededError:
        C.ok("context: budget too small raises BudgetExceededError", True)
    # L0 内容保留（如果存在）
    blk = pc.render_system_block(pm, "小明")
    if blk["L0"]:
        ctx = ca.assemble(pm, "小明", "在干嘛", budget=500)
        C.ok("context: L0 preserved under budget", "复合" in ctx["system_text"] or "棱角" in ctx["system_text"])


def t_context_deterministic():
    pm = sample_pm()
    a = ca.assemble(pm, "小明", "在干嘛", budget=1500)
    b = ca.assemble(pm, "小明", "在干嘛", budget=1500)
    C.ok("context: deterministic assembly", a["system_text"] == b["system_text"] and a["user_text"] == b["user_text"])


# ============ Determinism ============
def t_determinism_full():
    pm = sample_pm()
    outs = []
    for i in range(3):
        rt = make_runtime(pm)
        # 每次全新 session（同输入无历史干扰）；用"在干嘛"（无 proposal）
        r = rt.respond("在干嘛", session_id=f"det{i}")
        sig = json.dumps({k: r[k] for k in ("assistant_response", "used", "reality_flags")},
                         ensure_ascii=False, sort_keys=True)
        outs.append(sig)
    C.ok("determinism: same persona+msg+mock → identical (response/used/reality)",
         len(set(outs)) == 1, str(set(outs)))


def t_runtime_output_contract():
    rt = make_runtime()
    r = rt.respond("在干嘛", session_id="oc")
    for k in ("assistant_response", "used", "reality_flags", "session_update", "memory_proposals"):
        C.ok(f"output-contract: has {k}", k in r)
    C.ok("output-contract: used has provenance keys",
         {"persona_claims", "memory_items", "session_context_used"} <= set(r["used"].keys()))


def main():
    print("=== Persona Runtime 测试 (Stage 5.7) ===")
    tests = [
        ("retrieval: keyword/superseded/conflict", t_retrieval),
        ("retrieval: threshold", t_retrieval_threshold),
        ("retrieval: evolved valid_period", t_retrieval_evolved_history),
        ("G3-4: lifecycle status filtering", t_g3_lifecycle_filtering),
        ("G3-4: default_scorer unchanged", t_g3_default_scorer_unchanged),
        ("persona: layers", t_persona_layers),
        ("persona: sensitive preserved", t_sensitive_preserved),
        ("reality: 2022 vs 去年", t_reality_2022_vs_last_year),
        ("reality: question vs assertion vs guess vs correction", t_reality_question_not_assertion),
        ("reality: missing memory", t_reality_missing_memory),
        ("reality: conflict memory both", t_reality_conflict_memory),
        ("reality-runtime: post-filter", t_reality_old_as_current_postfilter),
        ("session: turns", t_session_turns),
        ("session: persistence", t_session_persistence),
        ("proposal: user fact only", t_proposal_user_fact),
        ("proposal: LLM not direct", t_proposal_llm_not_direct),
        ("correction: overlay + P1-A stable", t_correction_overlay),
        ("correction: missing target", t_correction_missing_target),
        ("gateway: mock", t_gateway_mock),
        ("gateway: retry", t_gateway_timeout_retry),
        ("gateway: fallback on error", t_gateway_fallback_on_gateway_error),
        ("context: budget L0 kept", t_context_budget_l0_never_dropped),
        ("context: deterministic", t_context_deterministic),
        ("determinism: full round", t_determinism_full),
        ("output contract", t_runtime_output_contract),
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
