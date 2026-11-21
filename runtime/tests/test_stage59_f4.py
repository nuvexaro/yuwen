#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 5.9-A1 F4：classify_user_message 顺序 + 反问/纠正边界（独立新增，不进 517 计数）。

顺序：correction → guess → question → assertion。
  - ? 不能覆盖明显 guess marker
  - 含“是不是”的问句不能被宽松的“不是”子串误判成 correction

锚点：
  “我们去年去过上海，对吧？”        → question
  “我们去年去过上海，可能吧？”      → guess
  “你是不是记错了？”                → question
  “我们去年是不是去过上海？”        → question
  “我们可能去年去过上海？”          → guess
  “我猜我们去年去过上海？”          → guess
  “我们去年去过上海。”              → assertion
  “不是，你记错了” / “不对，她其实特别话痨。” → correction
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.dirname(HERE)
for p in (RUNTIME,):
    if p not in sys.path:
        sys.path.insert(0, p)

import reality_boundary as rb  # noqa: E402


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


def check(text, expect, label):
    got = rb.classify_user_message(text)
    C.ok(f"F4: {label} → {expect}", got == expect, f"got {got}")


def main():
    print("=== Stage 5.9-A1 F4: correction/guess/question ordering ===")
    # 用户指定锚点
    check("我们去年去过上海，对吧？", "question", "对吧？question")
    check("我们去年去过上海，可能吧？", "guess", "可能吧？guess（不被?覆盖）")
    check("你是不是记错了？", "question", "是不是记错？question（不被误判 correction）")
    check("我们去年是不是去过上海？", "question", "是不是去过？question")
    check("我们可能去年去过上海？", "guess", "可能…？guess")
    check("我猜我们去年去过上海？", "guess", "我猜…？guess")
    check("我们去年去过上海。", "assertion", "陈述 assertion")
    check("不是，你记错了", "correction", "明确纠正 correction")
    check("不对，她其实特别话痨。", "correction", "不对纠正 correction")
    # guess 可带 ? 也可不带
    check("她可能不喜欢人多的地方。", "guess", "她可能…guess（无?）")
    # 回归锚点（不改变既有分类）
    check("在干嘛", "assertion", "寒暄 assertion")
    check("我们去年去上海了吗？", "question", "吗？question")
    check("我明天要去北京", "assertion", "陈述 assertion")
    check("你最近怎么样", "assertion", "问候 assertion")
    check("你现在是不是还和那个谁在一起？", "question", "是不是+那个谁 → question")
    print(f"\n通过 {C.ok_n} / 失败 {C.fail_n}")
    for f in C.fails:
        print("  -", f)
    sys.exit(0 if C.fail_n == 0 else 1)


if __name__ == "__main__":
    main()
