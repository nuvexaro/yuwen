#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v0.3.0：新信息提议（G3-3 new-fact proposal）裁决后不应逐轮重复询问。

背景：试用者反馈"每一次聊天他的纠正流程都会重新来一遍"。pilot 记录显示纠正本身写回成功，
抱怨来自 CLI 逐轮重复弹确认；纠正提议在 G3 已修（`_existing_proposals` + 幂等 confirm），
但**新信息提议**仍有同样问题：裁决后不从 `pending_confirmations` 移除，每轮重新询问。

覆盖：
  a) approve 后下一轮不再出现
  b) reject 后下一轮不再出现（且不写 canonical）
  c) 同一条重复 approve：只写一次，revision 只 +1
  d) 模拟 mvp_session 连续 3 轮：同一条提议只被询问 1 次
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
STAGE6 = os.path.dirname(HERE)
ROOT = os.path.dirname(STAGE6)
for _p in (os.path.join(ROOT, "tools"), os.path.join(ROOT, "runtime"), HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import skill_writer_v12 as sw12  # noqa: E402
from production_host import Host, HostError  # noqa: E402


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
            "persona": {"layer0_rules": {},
                        "identity": {"name_or_alias": {"value": "X", "claim_id": "pc_n"}}},
            "memory": {"core_facts": [], "preferences": [], "timeline": [],
                       "shared_experiences": [], "conflicts": [], "happy_memories": [],
                       "breakup": [], "inside_jokes": [], "daily_patterns": []},
            "corrections": []}


def mock_responder(prompt, **k):
    return "嗯。"


FACT = "她最爱喝咖啡"   # 能落 preferences 桶，因此会进入确认流程


def _new_host(tmp_root, slug):
    base = os.path.join(tmp_root, "exes")
    os.makedirs(base, exist_ok=True)
    if not os.path.exists(os.path.join(base, slug)):
        sw12.init_ex_instance(seed_pm(), base, slug)
    host = Host(base, adapter=mock_responder, model="mock",
                session_store_dir=os.path.join(tmp_root, "sessions"))
    return host, host.new_session(slug), os.path.join(base, slug, "persona_memory.json")


def t_approve_stops_reasking():
    tmp = tempfile.mkdtemp(prefix="mp_a_")
    try:
        host, sid, pm_path = _new_host(tmp, "demo")
        host.respond(sid, FACT)
        props = host.pending_memory_proposals(sid)
        C.ok("a: 产生新信息提议", len(props) == 1 and props[0]["text"] == FACT, str(props))
        if not props:
            return
        host.decide_memory_proposal(sid, props[0]["proposal_id"], True)
        host.respond(sid, "再聊聊别的")
        after = host.pending_memory_proposals(sid)
        C.ok("a: approve 后不再出现", all(p["text"] != FACT for p in after),
             str([p["text"] for p in after]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def t_reject_stops_reasking():
    tmp = tempfile.mkdtemp(prefix="mp_b_")
    try:
        host, sid, pm_path = _new_host(tmp, "demo")
        host.respond(sid, FACT)
        props = host.pending_memory_proposals(sid)
        if not props:
            C.ok("b: 产生新信息提议", False, "无提议")
            return
        before = json.load(open(pm_path, encoding="utf-8"))["revision"]
        host.decide_memory_proposal(sid, props[0]["proposal_id"], False)
        after_rev = json.load(open(pm_path, encoding="utf-8"))["revision"]
        C.ok("b: reject 不写 canonical", after_rev == before, f"{before} -> {after_rev}")
        host.respond(sid, "再聊聊别的")
        after = host.pending_memory_proposals(sid)
        C.ok("b: reject 后不再出现", all(p["text"] != FACT for p in after),
             str([p["text"] for p in after]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def t_double_approve_writes_once():
    tmp = tempfile.mkdtemp(prefix="mp_c_")
    try:
        host, sid, pm_path = _new_host(tmp, "demo")
        host.respond(sid, FACT)
        props = host.pending_memory_proposals(sid)
        if not props:
            C.ok("c: 产生新信息提议", False, "无提议")
            return
        pid = props[0]["proposal_id"]
        rev0 = json.load(open(pm_path, encoding="utf-8"))["revision"]
        host.decide_memory_proposal(sid, pid, True)
        rev1 = json.load(open(pm_path, encoding="utf-8"))["revision"]
        raised = None
        try:
            host.decide_memory_proposal(sid, pid, True)
        except HostError as e:
            raised = e
        rev2 = json.load(open(pm_path, encoding="utf-8"))["revision"]
        C.ok("c: 第一次 approve 写入一次", rev1 == rev0 + 1, f"{rev0} -> {rev1}")
        C.ok("c: 重复 approve 不再写", rev2 == rev1, f"{rev1} -> {rev2} (raised={raised})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def t_asked_only_once_over_three_turns():
    tmp = tempfile.mkdtemp(prefix="mp_d_")
    try:
        host, sid, pm_path = _new_host(tmp, "demo")
        asked = 0
        for i, msg in enumerate([FACT, "再聊聊别的", "还有呢"], 1):
            host.respond(sid, msg)
            props = host.pending_memory_proposals(sid)
            if any(p["text"] == FACT for p in props):
                asked += 1
            print(f"  第 {i} 轮：pending={[p['text'] for p in props]}")
        C.ok("d: 3 轮里只询问 1 次", asked == 1, f"实际询问 {asked} 次")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    print("=== 新信息提议生命周期测试（v0.3.0）===")
    t_approve_stops_reasking()
    t_reject_stops_reasking()
    t_double_approve_writes_once()
    t_asked_only_once_over_three_turns()
    print(f"\n通过 {C.ok_n} / 失败 {C.fail_n}")
    for f in C.fails:
        print("  -", f)
    sys.exit(0 if C.fail_n == 0 else 1)


if __name__ == "__main__":
    main()
