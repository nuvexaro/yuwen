#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 5.9-A2 F1：五态 Reality Boundary（独立新增，不进 517 计数）。

核心纪律：
  retrieval==empty 绝不能 => unsupported_claim。
  只有枚举 active persona memory 真空才能 unsupported_claim。
  memory 非空但召回缺失/不相关 => insufficient_evidence（不确认、不否认）。
  retrieval score≥0.2 不直接 = supported：需 subject_related 校验（拒单字“们”假阳性）。
  寒暄 / 情绪 / guess-特质（无实体共享事件） => ordinary，绝不误伤。

依赖 F4：guess marker 先于 question(?)。assess_support 依赖 classify_user_message。
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
import memory_retrieval as mr  # noqa: E402


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


def pm_with(*memory_items):
    pm = empty_pm()
    # 全部放 shared_experiences 便于构造
    pm["memory"]["shared_experiences"] = list(memory_items)
    return pm


def mi(id_, content, status="active", **kw):
    d = {"id": id_, "content": content, "status": status}
    d.update(kw)
    return d


def assess(pm, msg, flags=None, items=None, now=None):
    if flags is None:
        flags = rb.check_reality(pm, msg, now=now)
    return rb.assess_support(pm, msg, retrieved_items=items, now=now, flags=flags)


def main():
    print("=== Stage 5.9-A2 F1: five-state Reality Boundary ===")
    now = datetime(2026, 9, 1)

    # --- (1) 真空 empty → unsupported_claim（A 路径）---
    pm0 = empty_pm()
    s = assess(pm0, "我们去年去过上海，对吧？", now=now)
    C.ok("F1: empty+上海确认 → unsupported_claim", s["boundary_state"] == "unsupported_claim"
         and s["boundary_active"] is True, str(s))
    C.ok("F1: unsupported guard non-empty", bool(s["boundary_guard"]))
    s = assess(pm0, "我们当初怎么认识的", now=now)
    C.ok("F1: empty+相识问 → unsupported_claim", s["boundary_state"] == "unsupported_claim", str(s))

    # --- (2) conflicting：有 2022 记忆 + 去年(2025) → conflicting（B 路径）---
    pm1 = pm_with(mi("mi_sh", "2022年我们一起去过上海外滩", event_time="2022-06-01"))
    s = assess(pm1, "我们去年去上海玩了吧？", now=now)
    C.ok("F1: memory2022+去年 → conflicting", s["boundary_state"] == "conflicting"
         and s["boundary_active"] is True, str(s))
    C.ok("F1: conflicting guard empty (existing mechanism)", s["boundary_guard"] == "")

    # --- (3) supported：相关召回（外滩 ↔ 外滩），带 retrieval items（runtime 同款）---
    retr = mr.retrieve(pm1, {}, "还记得我们去外滩那次吗", k=5, now=now)
    C.ok("F1: retrieval recalls 外滩", len(retr["items"]) >= 1, str(retr["items"]))
    s = assess(pm1, "还记得我们去外滩那次吗", items=retr["items"], now=now)
    C.ok("F1: relevant recall → supported", s["boundary_state"] == "supported"
         and s["boundary_active"] is False, str(s))

    # --- (4) insufficient_evidence：memory 非空但召回不相关/缺失 ---
    # 4a: 内容“她住在上海”(无年份, 无 北京) + 用户“我们去年去过北京吧？”
    #     注：上海/北京 均含“海/京”… 但用户 query 与 memory “上海”无实质重叠（都是“去/北/京”
    #     之类），retrieval 对 北京 不召回“上海”→ 直接进 insufficient（不经 supported）
    pm2 = pm_with(mi("mi_home", "她住在上海"))
    s = assess(pm2, "我们去年去过北京吧？", now=now)
    C.ok("F1: nonempty-but-miss → insufficient_evidence（不否认）",
         s["boundary_state"] == "insufficient_evidence" and s["boundary_active"] is True, str(s))
    # 4b: 检索确实召回但不相关（“我们当初怎么认识的” 与 “2022外滩”仅“们”1 字重叠 0.383）
    pm3 = pm_with(mi("mi_sh2", "2022年我们一起去过上海外滩", event_time="2022-06-01"))
    retr = mr.retrieve(pm3, {}, "我们当初怎么认识的", k=5, now=now)
    C.ok("F1: retrieval DID recall on 1-char overlap", len(retr["items"]) == 1, str(retr["items"]))
    s = assess(pm3, "我们当初怎么认识的", items=retr["items"], now=now)
    C.ok("F1: single-char overlap NOT supported → insufficient_evidence",
         s["boundary_state"] == "insufficient_evidence", str(s))

    # --- (5) ordinary：寒暄/情绪/guess-特质（无共享实体）绝不误伤 ---
    for msg in ("在干嘛", "你最近怎么样", "哈哈 笑死我了", "现在过得怎么样", "晚安",
                "你可能不太喜欢人多的地方吧？"):
        s = assess(pm0, msg, now=now)
        C.ok(f"F1: ordinary [{msg}]", s["boundary_state"] == "ordinary"
             and s["boundary_active"] is False, str(s))

    print(f"\n通过 {C.ok_n} / 失败 {C.fail_n}")
    for f in C.fails:
        print("  -", f)
    sys.exit(0 if C.fail_n == 0 else 1)


if __name__ == "__main__":
    main()
