#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 5.9-A3/A4 F2+F3：boundary_active 门控 + deterministic confirmation detection。

F2：post-filter 门控 = boundary_active（conflicting OR insufficient_evidence OR unsupported_claim）
    guardrail 在 boundary_guard 时注入；supported/ordinary 不触发。
F3：_detect_confirmation(reply, flags)：只在 boundary_active 轮调用；不做“看到嗯=确认”。

依赖：F1（reality_boundary.assess_support）已实现、F4（classify）已实现。
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.dirname(HERE)
for p in (RUNTIME,):
    if p not in sys.path:
        sys.path.insert(0, p)

import reality_boundary as rb  # noqa: E402
import persona_constraints as pc  # noqa: E402
from persona_runtime import _detect_confirmation  # noqa: E402


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


def empty_pm():
    return {"schema_version": "1.2", "persona": {}, "memory": {
        k: [] for k in ("preferences", "timeline", "shared_experiences", "conflicts",
                        "happy_memories", "breakup", "inside_jokes", "core_facts",
                        "daily_patterns")}, "corrections": []}


def pm_with(*items):
    pm = empty_pm()
    pm["memory"]["shared_experiences"] = list(items)
    return pm


def mi(id_, content, **kw):
    d = {"id": id_, "content": content, "status": "active"}
    d.update(kw)
    return d


def support_of(pm, msg, items=None, now=None):
    fl = rb.check_reality(pm, msg, now=now)
    return rb.assess_support(pm, msg, retrieved_items=items, now=now, flags=fl)


def main():
    print("=== Stage 5.9-A3/A4 F2+F3: gate + confirmation detection ===")
    now = datetime(2026, 9, 1)

    # ============ F2: guardrail 注入 ============
    # unsupported_claim → boundary_guard 非空 → render 进 system
    pm0 = empty_pm()
    su = support_of(pm0, "我们去年去过上海，对吧？", now=now)
    C.ok("F2: unsupported boundary_active", su["boundary_active"] is True, str(su))
    blk = pc.render_system_block(pm0, "小明", reality_flags=su)
    C.ok("F2: unsupported guardrail injected into guard", "现实边界提醒" in blk["guardrail"]
         and "不记得" in blk["guardrail"], blk["guardrail"][:120])

    # conflicting → 仍由现有 reality_conflict 机制渲染（guard 空避免双份）
    pm1 = pm_with(mi("mi_sh", "2022年我们一起去过上海外滩", event_time="2022-06-01"))
    sc = support_of(pm1, "我们去年去上海玩了吧？", now=now)
    C.ok("F2: conflicting boundary_active", sc["boundary_state"] == "conflicting"
         and sc["boundary_active"] is True and sc["boundary_guard"] == "", str(sc))

    # insufficient_evidence → guardrail 注入
    pm2 = pm_with(mi("mi_home", "她住在上海"))
    si = support_of(pm2, "我们去年去过北京吧？", now=now)
    C.ok("F2: insufficient boundary_active + guardrail", si["boundary_active"] is True
         and bool(si["boundary_guard"]), str(si))
    blk2 = pc.render_system_block(pm2, "小明", reality_flags=si)
    C.ok("F2: insufficient guardrail injected", "现实边界提醒" in blk2["guardrail"], blk2["guardrail"][:100])

    # supported / ordinary → 不注入
    import memory_retrieval as mr
    retr = mr.retrieve(pm1, {}, "还记得我们去外滩那次吗", k=5, now=now)
    ss = support_of(pm1, "还记得我们去外滩那次吗", items=retr["items"], now=now)
    C.ok("F2: supported NOT active", ss["boundary_state"] == "supported" and ss["boundary_active"] is False, str(ss))
    so = support_of(pm0, "在干嘛", now=now)
    C.ok("F2: ordinary NOT active", so["boundary_state"] == "ordinary" and so["boundary_active"] is False, str(so))

    # ============ F3: confirmation detection 清单 ============
    # boundary-active flags（模拟 unsupported 上海 + insufficient 北京 + conflicting 外滩）
    flag_unsup = {"boundary_active": True, "contested": "我们去年去过上海，对吧？"}
    flag_conf  = {"boundary_active": True, "contested": "我们去年去上海玩了吧？"}
    flag_insuf = {"boundary_active": True, "contested": "我们去年去过北京吧？"}

    # 应拦截（confirmation of contested fact）
    intercept = [
        ("嗯 去过", flag_unsup), ("去过啊", flag_unsup), ("对，去年去过外滩", flag_conf),
        ("嗯 就是去年去的", flag_conf), ("对，是去过", flag_conf), ("嗯 去过了", flag_unsup),
        ("嗯 去过外滩 那会儿风挺大的", flag_conf),
    ]
    for txt, fl in intercept:
        C.ok(f"F3: INTERCEPT {txt!r}", _detect_confirmation(txt, fl) is True, _detect_confirmation(txt, fl))
    # 不应拦截
    allow = [
        ("可能吧", flag_unsup), ("好像是", flag_conf), ("大概去过吧", flag_conf),
        ("我不太记得了", flag_unsup), ("我忘了", flag_unsup), ("不太确定", flag_conf),
        ("嗯 怎么突然问这个", flag_unsup), ("嗯 知道了", flag_unsup),
        ("嗯 记得", flag_unsup),   # 无对象“记得”语义不足 → 不拦
        ("记不清了 都过去多久了", flag_conf),
        ("你说的是哪次？", flag_unsup),   # 反问不确认
        ("没什么印象", flag_unsup),
    ]
    for txt, fl in allow:
        got = _detect_confirmation(txt, fl)
        C.ok(f"F3: ALLOW {txt!r}", got is False, got)

    # F3 仅在 boundary_active 轮被调用（门在 runtime），此处单测已覆盖其判定本身。

    print(f"\n通过 {C.ok_n} / 失败 {C.fail_n}")
    for f in C.fails:
        print("  -", f)
    sys.exit(0 if C.fail_n == 0 else 1)


if __name__ == "__main__":
    main()
