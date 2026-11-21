#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""确定性 mock responder（供 gateway 注入，5.6/测试用）。

可按 L2 风格做轻量模板（示例：若系统块含某口头禅则拼进回复），
但保持 deterministic——只为测试/评测，不是产品回复质量目标。
"""

from __future__ import annotations


def simple_responder(prompt: str, *, model=None, max_tokens=None, temperature=None) -> str:
    """回一个固定、带人格味的占位回复（引用系统里出现的口头禅如存在）。"""
    catch = None
    for marker in ("哈哈哈哈", "hh", "嗯嗯", "哦", "嘿嘿"):
        if marker in prompt:
            catch = marker
            break
    base = "哦，这样啊。"
    if catch:
        base = f"{catch} 这样啊。"
    # 若系统块含"不想说"类 reality 冲突提醒 → 回不确定
    if "现实边界提醒" in prompt or "不确定" in prompt:
        base = "……我不太确定。你具体指的是哪次？"
    return base
