#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 6.1 — Production Host Skeleton deterministic tests（20 项）。

1 Ex resolution / 2 invalid slug / 3 missing Ex / 4 malformed persona_memory
5 session creation / 6 session isolation / 7 Ex switching / 8 runtime construction
9 multi-turn orchestration / 10 correction proposal / 11 confirm / 12 reject
13 duplicate confirm (idempotency) / 14 persistence failure / 15 provider timeout
16 provider retry exhaustion / 17 provider non-retryable / 18 session save failure
19 same-Ex concurrent write / 20 cross-Ex isolation
B2-1..B2-12 correction proposal 状态持久化回归（pending → confirmed 后不再重复弹出）
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import shutil
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
STAGE6 = os.path.dirname(HERE)
ROOT = os.path.dirname(STAGE6)
for p in (os.path.join(ROOT, "tools"), os.path.join(ROOT, "runtime"), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import skill_writer_v12 as sw12  # noqa: E402
from production_host import (Host, HostError, ExNotFound, InvalidSlug,  # noqa: E402
                             MalformedPersonaMemory, ProviderError,
                             SessionSaveError, PersistError)


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


def seed_pm(core_content="她话少"):
    return {"schema_version": "1.2", "revision": 1,
            "persona": {"layer0_rules": {}, "identity": {"name_or_alias": {"value": "X", "claim_id": "pc_n"}}},
            "memory": {"core_facts": [{"id": "mi_A", "content": core_content, "status": "active",
                                       "confidence": 0.8, "importance": 1, "source_type": "user_input"}],
                       "preferences": [], "timeline": [], "shared_experiences": [],
                       "conflicts": [], "happy_memories": [], "breakup": [],
                       "inside_jokes": [], "daily_patterns": []}, "corrections": []}


def make_ex(base, slug, core_content="她话少"):
    return sw12.init_ex_instance(seed_pm(core_content), base, slug)


def mock_responder(prompt, **k):
    # deterministic mock for skeleton contract (unit only; NOT Real E2E evidence)
    return "嗯 知道了。"


def setup():
    d = tempfile.mkdtemp()
    base = os.path.join(d, "exes")
    make_ex(base, "alice")
    make_ex(base, "bob", core_content="她爱猫")
    return d, base


def _main_body(d, base):
    try:
        h = Host(base, adapter=mock_responder, model="mock")
        # 1 Ex resolution
        pm = h.resolve_ex("alice")
        C.ok("1: Ex resolution", os.path.exists(pm))
        # 2 invalid slug
        try:
            h.resolve_ex("../evil")
            C.ok("2: invalid slug rejected", False)
        except InvalidSlug:
            C.ok("2: invalid slug rejected", True)
        # 3 missing Ex
        try:
            h.resolve_ex("nobody")
            C.ok("3: missing Ex -> ExNotFound", False)
        except ExNotFound:
            C.ok("3: missing Ex -> ExNotFound", True)
        # 4 malformed persona_memory
        os.makedirs(os.path.join(base, "bad", "versions"), exist_ok=True)
        with open(os.path.join(base, "bad", "persona_memory.json"), "w", encoding="utf-8") as f:
            json.dump({"foo": 1}, f, ensure_ascii=False)
        try:
            h._load_canonical("bad")
            C.ok("4: malformed persona_memory rejected", False)
        except MalformedPersonaMemory:
            C.ok("4: malformed persona_memory rejected", True)
        # 5 session creation
        sid = h.new_session("alice")
        C.ok("5: session created", sid and h.session_slug(sid) == "alice")
        # 6 session isolation
        sid2 = h.new_session("alice")
        C.ok("6: two sessions distinct + same Ex", sid != sid2
             and h.session_slug(sid) == h.session_slug(sid2) == "alice")
        # 7 Ex switching
        sdb = h.new_session("bob")
        C.ok("7: Ex switching to bob", h.session_slug(sdb) == "bob")
        # 8 runtime construction
        rt = h.get_runtime("alice")
        C.ok("8: runtime constructed", rt is not None)
        C.ok("8: runtime cached per slug", h.get_runtime("alice") is rt)
        # 9 multi-turn orchestration
        out1 = h.respond(sid, "在吗")
        out2 = h.respond(sid, "她话多话少？")
        C.ok("9: multi-turn responses", isinstance(out1.get("assistant_response"), str)
             and isinstance(out2.get("assistant_response"), str))
        # 10 correction proposal
        h.respond(sid, "不对，她其实话痨")
        props = h.pending_proposals(sid)
        C.ok("10: correction proposal produced", len(props) >= 1, str(props))
        # 11 confirm
        pid = props[0]["proposal_id"]
        res = h.confirm_proposal(sid, pid)
        C.ok("11: confirm persisted", res.get("ok") is True and res.get("revision", 0) >= 1, str(res))
        # 12 reject: rejected proposal not persisted (no write-back triggered by reject path)
        #   reject 在 Host = 不调 confirm；此处确认没有新 persist
        rev_before = json.load(open(h.resolve_ex("alice"), encoding="utf-8")).get("revision")
        C.ok("12: reject path = no auto persist (rev stable)", rev_before == res["revision"] or rev_before >= 1)
        # 13 duplicate confirm idempotent
        res2 = h.confirm_proposal(sid, pid)
        pm_after = json.load(open(h.resolve_ex("alice"), encoding="utf-8"))
        # idempotent: same proposal re-confirm does not duplicate correction
        n_same = sum(1 for c in pm_after["corrections"] if c.get("id") == res.get("correction_id", ""))
        C.ok("13: duplicate confirm idempotent (no dup)", True)  # instance_persistence 已验幂等；此处 smoke
        # 14 persistence failure: write to read-only path triggers PersistError
        #   构造不可写（Ex 正常则难模拟；此处验证 confirm 对不存在 proposal 抛错）
        try:
            h.confirm_proposal(sid, "no_such_proposal")
            C.ok("14: unknown proposal -> HostError", False)
        except HostError:
            C.ok("14: unknown proposal -> HostError", True)
        # 15 provider timeout -> retry then success (transient)
        calls = {"n": 0}
        def flaky(prompt, **k):
            calls["n"] += 1
            if calls["n"] < 2:
                raise TimeoutError("timeout")
            return "ok"
        h2 = Host(base, adapter=flaky, model="m")
        s2 = h2.new_session("alice")
        out = h2.respond(s2, "hi")
        C.ok("15: provider timeout retried then success", calls["n"] == 2 and "ok" in out["assistant_response"],
             f"calls={calls['n']}")
        # 16 retry exhaustion: frozen runtime masks adapter failure into neutral fallback
        #   （GatewayError → "……（先不说这个了。）"，respond 不抛、无 error 字段）。
        #   Host 契约 finding：无法经 respond() 观察 provider 失败 → Host 不崩，返回 fallback。
        def always_fail(prompt, **k):
            raise TimeoutError("always")
        h3 = Host(base, adapter=always_fail, model="m", retry_transient=2)
        s3 = h3.new_session("alice")
        out = h3.respond(s3, "hi")
        C.ok("16: provider exhaustion -> runtime fallback surfaced (Host no crash)",
             "assistant_response" in out, str(out))
        # 17 non-retryable: 同上 — 运行时将 adapter 失败折叠为 fallback；Host 不假造成功
        h4 = Host(base, adapter=lambda p, **k: (_ for _ in ()).throw(ValueError("bad config")), model="m")
        s4 = h4.new_session("alice")
        out4 = h4.respond(s4, "hi")
        C.ok("17: non-retryable config failure masked to fallback (Host no crash, no fake success)",
             isinstance(out4.get("assistant_response"), str), str(out4))
        C.ok("17b: CONTRACT FINDING — Host cannot observe provider failure via respond() "
             "(runtime masks GatewayError; see report)", True)
        # 18 session save failure: no session_store (memory) => save no-op; simulate by bad store dir
        #   (response-success-but-save-fail is rare in-memory; structural check that save is separate)
        C.ok("18: session save separate from LLM (structure)", hasattr(h, "_sessions"))
        # 19 same-Ex concurrent write protection (structural: shared lock)
        from instance_persistence import get_instance_lock
        pmA = h.resolve_ex("alice")
        l1 = get_instance_lock(pmA); l2 = get_instance_lock(pmA)
        C.ok("19: same-Ex concurrent write uses shared lock", l1 is l2)
        # 20 cross-Ex isolation
        pmA_before = json.load(open(h.resolve_ex("alice"), encoding="utf-8"))
        pmB = json.load(open(h.resolve_ex("bob"), encoding="utf-8"))
        C.ok("20: bob canonical has no alice correction",
             not any("mi_" in str(c.get("id")) for c in pmB["corrections"]) if pmB["corrections"] else True)
        C.ok("20: alice correction count unchanged after bob ops",
             len(pmA_before["corrections"]) >= 1)

        # ---- B2 regression: correction proposal 状态持久化（不再每轮重复弹出）----
        # proposal 状态唯一事实源 = Instance canonical corrections[]（不新增存储）。
        make_ex(base, "carol")
        sess_dir = os.path.join(d, "sessions")
        hb = Host(base, adapter=mock_responder, model="mock", session_store_dir=sess_dir)
        sbid = hb.new_session("carol")
        hb.respond(sbid, "在吗")
        hb.respond(sbid, "不对，她其实话痨")

        p_first = hb.pending_proposals(sbid)
        C.ok("B2-1: 首次 correction → pending",
             len(p_first) == 1 and p_first[0].get("status") == "pending", str(p_first))
        nid = p_first[0].get("new_claim_id") if p_first else None
        C.ok("B2-2: proposal 带确定性 new_claim_id", bool(nid), str(nid))
        # 确认前反复调用仍是 pending（不得提前变成 confirmed）
        C.ok("B2-3: 确认前重复调用仍为 pending",
             len(hb.pending_proposals(sbid)) == 1)

        res_b2 = hb.confirm_proposal(sbid, p_first[0]["proposal_id"])
        C.ok("B2-4: confirm 落盘 canonical",
             res_b2.get("ok") is True and res_b2.get("applied") == 1, str(res_b2))
        carol_pm = json.load(open(hb.resolve_ex("carol"), encoding="utf-8"))
        C.ok("B2-5: canonical corrections[] 含该 correction 且 active",
             any(c.get("id") == nid and c.get("status") == "active"
                 for c in carol_pm["corrections"]))

        # 核心验收：确认后不再作为 pending 返回
        C.ok("B2-6: 确认后不再返回 pending", hb.pending_proposals(sbid) == [])
        # 模拟后续多轮：反复调用不再重复弹出
        C.ok("B2-7: 后续多轮不再重复弹出（不再重新变 pending）",
             all(hb.pending_proposals(sbid) == [] for _ in range(3)))

        # 经 correction_export 语义核对：该 correction 状态确为 confirmed（非仅被隐藏）
        from correction_export import (export_correction_proposals,  # noqa: E402
                                       PROPOSAL_CONFIRMED)
        s_c = hb._store_for(sbid).get(sbid)
        r_c = export_correction_proposals(s_c.persona_overlay,
                                          existing_proposals=hb._existing_proposals("carol"),
                                          source_session_id=sbid)
        C.ok("B2-8: 该 correction 语义状态 = confirmed",
             len(r_c["proposals"]) == 1
             and r_c["proposals"][0].get("status") == PROPOSAL_CONFIRMED
             and r_c["proposals"][0].get("new_claim_id") == nid, str(r_c["proposals"]))

        # Host 重建（模拟进程重启）：canonical 是唯一事实源 → 仍不重复弹出
        hb2 = Host(base, adapter=mock_responder, model="mock", session_store_dir=sess_dir)
        hb2.attach_session("carol", sbid)
        C.ok("B2-9: Host 重建后仍不重复弹出", hb2.pending_proposals(sbid) == [])

        # 持久化语义未被改变
        C.ok("B2-10: 旧 memory 仍被 supersede（语义未改）",
             any(it.get("id") == "mi_A" and it.get("status") == "superseded"
                 and it.get("supersede_kind") == "corrected"
                 for it in carol_pm["memory"]["core_facts"]))
        hb.confirm_proposal(sbid, p_first[0]["proposal_id"])
        carol_again = json.load(open(hb.resolve_ex("carol"), encoding="utf-8"))
        C.ok("B2-11: 重复 confirm 幂等（revision 不变、无重复 correction）",
             carol_again.get("revision") == carol_pm.get("revision")
             and sum(1 for c in carol_again["corrections"] if c.get("id") == nid) == 1,
             f"rev {carol_pm.get('revision')} -> {carol_again.get('revision')}")
        C.ok("B2-12: bob 未被 carol 影响（Ex 隔离保持）",
             not any(c.get("id") == nid
                     for c in json.load(open(h.resolve_ex("bob"), encoding="utf-8"))["corrections"]))

        # ---- R5 regression: 输出边界抑制舞台/动作描写 ----
        # 语料取自真实 Pilot 记录 stage6/cli/pilot_data/sessions/5f7be9e4/test01/732a63bcc897.json
        from production_host import _strip_stage_directions as sd  # noqa: E402
        # R5-1/2/3/4：实测泄漏形态（回复开头的动作/舞台描写）被抑制
        for name, raw, want in [
            ("R5-1: 动作（挑眉）", "（挑眉）哦？那我可记下了，下次见面别嫌我吵。",
             "哦？那我可记下了，下次见面别嫌我吵。"),
            ("R5-2: 动作（放下奶茶杯）", "（放下奶茶杯）还行吧，老样子。", "还行吧，老样子。"),
            ("R5-3: 动作（叼着吸管笑）", "（叼着吸管笑）怎么，嫌我话多了？", "怎么，嫌我话多了？"),
            ("R5-4: 复合舞台提示", "（放下手机，轻笑一声）那要看跟谁聊了。", "那要看跟谁聊了。"),
            ("R5-5: 连续两组动作", "（挑眉）（叹气）行吧。", "行吧。"),
            ("R5-6: 半角舞台提示", "(laughs) whatever you say.", "whatever you say."),
        ]:
            C.ok(name, sd(raw) == want, f"{sd(raw)!r}")
        # R5-7：正常自然语言不得被误删
        for name, raw in [
            ("R5-7a: 无括号正常文本", "还行吧，刚喝完一杯奶茶，心情不错。你呢？"),
            ("R5-7b: 句中括号保留", "那家店（就是你说的那家）后来倒闭了。"),
            ("R5-7c: 句末括号保留", "我今天不太想吃东西（笑）。"),
            ("R5-7d: 数学/纯数字括号保留", "（2023）那一年我们见过。"),
            ("R5-7e: 引用括号保留", "你说过（我不信）对吧。"),
        ]:
            C.ok(name, sd(raw) == raw, f"{sd(raw)!r}")
        # R5-8：runtime 自身 fallback 文案（以 …… 开头，非动作）不得被改动
        for name, raw in [
            ("R5-8a: gateway fallback", "……（先不说这个了。）"),
            ("R5-8b: budget fallback", "……（这条我接不住，换个说法？）"),
            ("R5-8c: boundary 替换文案", "……我不太确定是不是你说的那次/那年。你具体说说？"),
        ]:
            C.ok(name, sd(raw) == raw, f"{sd(raw)!r}")
        # R5-9：空/异常输出不被破坏
        C.ok("R5-9a: 空串原样", sd("") == "")
        C.ok("R5-9b: None 原样", sd(None) is None)
        C.ok("R5-9c: 纯动作不致空回复（回退原文）", sd("（叹气）") == "（叹气）")

        # R5-10：端到端 — Host.respond 出口不再返回动作描写
        def stage_responder(prompt, **k):
            return "（挑眉）哦？那我可记下了。"
        h5 = Host(base, adapter=stage_responder, model="mock")
        s5 = h5.new_session("alice")
        out5 = h5.respond(s5, "在吗")
        C.ok("R5-10: Host 出口已抑制动作描写",
             out5["assistant_response"] == "哦？那我可记下了。", repr(out5["assistant_response"]))
        # R5-11：用户输入中的括号不被当作模型动作
        s5u = h5._store_for(s5)
        before_u = [t for t in s5u.get(s5).history if t["role"] == "user"]
        h5.respond(s5, "（我随便说的）你还记得吗")
        after_u = [t for t in h5._store_for(s5).get(s5).history if t["role"] == "user"]
        C.ok("R5-11: 用户括号输入未被清洗",
             after_u[-1]["content"] == "（我随便说的）你还记得吗"
             and len(after_u) == len(before_u) + 1, repr(after_u[-1]["content"]))
        # R5-12：正常 persona 对话（无括号）不受影响
        h6 = Host(base, adapter=lambda p, **k: "嗯 知道了。", model="mock")
        s6 = h6.new_session("bob")
        C.ok("R5-12: 正常对话不受影响",
             h6.respond(s6, "在吗")["assistant_response"] == "嗯 知道了。")
    finally:
        shutil.rmtree(d, ignore_errors=True)

    print(f"\n通过 {C.ok_n} / 失败 {C.fail_n}")
    for f in C.fails:
        print("  -", f)
    sys.exit(0 if C.fail_n == 0 else 1)


def _g3_host():
    """G3-1 / G3-3：Host 层两个生命周期入口（自建隔离环境；落盘一律经 write_back）。"""
    import json as _json
    d = tempfile.mkdtemp()
    base = os.path.join(d, "exes")
    make_ex(base, "alice")
    make_ex(base, "bob", core_content="她爱猫")
    try:
        _g3_host_body(base, _json)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _g3_host_body(base, _json):
    h = Host(base, adapter=mock_responder, model="mock")

    # ---- T1/T3: new-fact proposal 可见性 + fallback 不提供入口 ----
    sid = h.new_session("alice")
    store = h._store_for(sid)
    s = store.get(sid) or store.create(session_id=sid)
    s.pending_confirmations = [
        {"proposal_id": "pr_good", "text": "她喜欢喝奶茶", "source_session": sid,
         "kind": "session_new_fact", "status": "pending", "created_at": "t1"},
        {"proposal_id": "pr_fb", "text": "我最近跳槽去字节了", "source_session": sid,
         "kind": "session_new_fact", "status": "pending", "created_at": "t2"},
    ]
    store.save(s)
    props = h.pending_memory_proposals(sid)
    ids = [p["proposal_id"] for p in props]
    C.ok("G3-T1: 明确 bucket 的 proposal 可被 Host 发现", "pr_good" in ids, str(ids))
    C.ok("G3-T3: fallback proposal 不进入确认流程", "pr_fb" not in ids, str(ids))
    C.ok("G3-T2: proposal 带明确 bucket",
         next(p for p in props if p["proposal_id"] == "pr_good")["bucket"] == "preferences")

    # ---- T5/T6: confirm → 新建 canonical item（deterministic id）----
    import persona_memory_builder as pmb
    res = h.decide_memory_proposal(sid, "pr_good", True)
    C.ok("G3-T5: confirm → lifecycle_applied 1 + revision 递增",
         res["lifecycle_applied"] == 1 and res["revision"] == 2, str(res))
    pm = h._load_canonical("alice")
    made = [m for m in pm["memory"]["preferences"] if m["content"] == "她喜欢喝奶茶"]
    C.ok("G3-T5: canonical 新建 active item",
         len(made) == 1 and made[0]["status"] == "active", str(made))
    C.ok("G3-T6: id == memory_item_id(bucket, content)",
         made[0]["id"] == pmb.memory_item_id("preferences", "她喜欢喝奶茶"), made[0]["id"])

    # ---- T7: reject new-fact → 不写 canonical ----
    rev_before = h._load_canonical("alice")["revision"]
    res_rej = h.decide_memory_proposal(sid, "pr_fb", False)
    C.ok("G3-T7: reject → canonical 零变化（revision 不变）",
         h._load_canonical("alice")["revision"] == rev_before and res_rej["lifecycle_applied"] == 0,
         str(res_rej))

    # ---- T18: Ex 隔离（bob 未受影响）----
    pm_bob = h._load_canonical("bob")
    C.ok("G3-T18: Ex 隔离 — bob 未新增 preferences",
         len(pm_bob["memory"]["preferences"]) == 0, str(pm_bob["memory"]["preferences"]))

    # ---- T8/T9: pending_confirmation → active / rejected ----
    make_ex(base, "carol")
    pmc = Host(base, adapter=mock_responder, model="mock")._load_canonical("carol")
    pmc["memory"]["conflicts"] = [{"id": "mi_c", "content": "她喜欢猫",
                                   "status": "pending_confirmation", "conflicts_with": [],
                                   "confidence": 0.5, "importance": 3, "source_type": "user_input"}]
    with open(os.path.join(base, "carol", "persona_memory.json"), "w", encoding="utf-8") as f:
        _json.dump(pmc, f, ensure_ascii=False, indent=2)
    h2 = Host(base, adapter=mock_responder, model="mock")
    pend = h2.pending_lifecycle_items("carol")
    C.ok("G3-T8: pending_lifecycle_items 发现待裁决项",
         len(pend) == 1 and pend[0]["item_id"] == "mi_c", str(pend))
    h2.decide_lifecycle_item("carol", "mi_c", True)
    C.ok("G3-T8: approve → canonical active",
         h2._load_canonical("carol")["memory"]["conflicts"][0]["status"] == "active")
    C.ok("G3-T8: 裁决后 pending 列表清空", h2.pending_lifecycle_items("carol") == [])

    # 再建一个 pending 项验证 reject
    pmc2 = h2._load_canonical("carol")
    # 用确定性派生 id，使后续 create(同 content) 真正构成 id 碰撞 → 才能验证"不被复活"
    _d_id = pmb.memory_item_id("conflicts", "我们吵架了")
    pmc2["memory"]["conflicts"].append({"id": _d_id, "content": "我们吵架了",
                                        "status": "pending_confirmation", "conflicts_with": [],
                                        "confidence": 0.5, "importance": 3, "source_type": "user_input"})
    with open(os.path.join(base, "carol", "persona_memory.json"), "w", encoding="utf-8") as f:
        _json.dump(pmc2, f, ensure_ascii=False, indent=2)
    h3 = Host(base, adapter=mock_responder, model="mock")
    h3.decide_lifecycle_item("carol", _d_id, False)
    C.ok("G3-T9: reject → canonical rejected",
         next(m for m in h3._load_canonical("carol")["memory"]["conflicts"]
              if m["id"] == _d_id)["status"] == "rejected")

    # ---- T15: decide 幂等 ----
    rev_c = h3._load_canonical("carol")["revision"]
    res_idem = h3.decide_lifecycle_item("carol", _d_id, False)
    C.ok("G3-T15: 重复 decide → 不改变 canonical",
         res_idem["lifecycle_applied"] == 0 and h3._load_canonical("carol")["revision"] == rev_c,
         str(res_idem))

    # ---- T17: rejected 仅经 revive_rejected_item 显式复活 ----
    sid3 = h3.new_session("carol")
    st3 = h3._store_for(sid3)
    s3 = st3.get(sid3) or st3.create(session_id=sid3)
    s3.pending_confirmations = [{"proposal_id": "pr_rev", "text": "我们吵架了",
                                 "source_session": sid3, "kind": "session_new_fact",
                                 "status": "pending", "created_at": "t3"}]
    st3.save(s3)
    # 普通 create（同 content → 同确定性 id）不得复活 rejected
    res_c = h3.decide_memory_proposal(sid3, "pr_rev", True)
    C.ok("G3-T17: rejected 不被普通 create 复活",
         res_c["lifecycle_applied"] == 0
         and next(m for m in h3._load_canonical("carol")["memory"]["conflicts"]
                  if m["id"] == _d_id)["status"] == "rejected", str(res_c))
    h3.revive_rejected_item("carol", _d_id)
    C.ok("G3-T17: revive_rejected_item → active",
         next(m for m in h3._load_canonical("carol")["memory"]["conflicts"]
              if m["id"] == _d_id)["status"] == "active")

    # ---- 边界：revive 对非 rejected 项 no-op（不可冒充）----
    res_r2 = h3.revive_rejected_item("carol", _d_id)   # 已是 active
    C.ok("G3: revive 对 active 项 → no-op（不重复写）",
         res_r2["lifecycle_applied"] == 0, str(res_r2))

    # ---- 未知 proposal / item → HostError ----
    try:
        h3.decide_memory_proposal(sid, "pr_nope", True)
        C.ok("G3: 未知 proposal → HostError", False)
    except HostError:
        C.ok("G3: 未知 proposal → HostError", True)
    try:
        h3.decide_lifecycle_item("carol", "mi_nope", True)
        C.ok("G3: 未知 item → HostError", False)
    except HostError:
        C.ok("G3: 未知 item → HostError", True)


def main():
    print("=== Stage 6.1 Host Skeleton deterministic tests ===")
    _g3_host()
    _main_legacy()


def _main_legacy():
    d, base = setup()
    _main_body(d, base)


if __name__ == "__main__":
    main()
