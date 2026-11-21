#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Context Assembly（deterministic token budget）。

禁止全量塞 persona_memory。固定预算；裁剪顺序：
  examples → L4 detail → low-relevance memory → 非 sensitive L3 → 旧 session。
L0 / reality(guardrail) / L1 identity / 当前 user message 永不可裁剪。
输出 system + user 两组 ChatMessage。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from llm_gateway import ChatMessage
from persona_constraints import render_system_block

# 简易 token 估算：中英混合 ~ 1 字≈0.7 token；按字符数估算，确定性。
def _est(text: str) -> int:
    return int(len(text) * 0.7) + 1


class BudgetExceededError(Exception):
    pass


def assemble(persona_memory: dict, name: str, user_message: str,
             retrieved: Optional[dict] = None, session_recent: Optional[List[dict]] = None,
             reality_flags: dict = None, budget: int = 2000,
             session_overlay: Optional[List[dict]] = None) -> Dict:
    """返回 {system_text, user_text, used:{persona_claims, memory_items, session_context_used}}。

    persona_claims: 本系统块实际引用的 claim value 列表（供 provenance 记录 value 级）。
    session_overlay（Stage 5.9-B F5-c）：传给 render_system_block 作【用户纠正】must-keep 块。
    """
    blocks = render_system_block(persona_memory, name, reality_flags,
                                 session_overlay=session_overlay)
    used_claims = []
    reserved_user = _est(user_message)
    # 不可裁剪块：guardrail + L0 + L1
    must_keep = "\n\n".join([b for b in
                             ["【规则】" + blocks["guardrail"],
                              "【绝不能做/人格棱角】" + blocks["L0"] if blocks["L0"] else "",
                              "【身份】" + blocks["L1"] if blocks["L1"] else ""] if b])
    must_tokens = _est(must_keep) + reserved_user
    if must_tokens > budget:
        raise BudgetExceededError("预算过小，无法容纳 L0/reality/L1/当前消息")

    # 记录 used claims
    layers = {"L0": blocks["L0"], "L1": blocks["L1"]}
    for k, v in layers.items():
        if v:
            used_claims.extend([ln for ln in v.splitlines() if ln.startswith("- ")][:20])

    # 可裁块按优先级加入
    remaining = budget - must_tokens
    parts = []
    # 顺序：L2, L3(先 sensitive), L4, memory, session
    l2 = "【说话风格】\n" + blocks["L2"] if blocks["L2"] else ""
    l3 = "【情绪模式】\n" + blocks["L3"] if blocks["L3"] else ""
    l4 = "【关系行为】\n" + blocks["L4"] if blocks["L4"] else ""

    def try_add(text, label):
        nonlocal remaining, parts
        if not text:
            return
        tok = _est(text)
        if tok <= remaining:
            parts.append(text)
            remaining -= tok
            if label == "L2":
                used_claims.extend([ln for ln in blocks["L2"].splitlines() if ln.startswith("- ")][:15])
            elif label == "L3":
                used_claims.extend([ln for ln in blocks["L3"].splitlines() if ln.startswith("- ")][:15])
            elif label == "L4":
                used_claims.extend([ln for ln in blocks["L4"].splitlines() if ln.startswith("- ")][:10])
        return tok <= 0

    try_add(l2, "L2")
    try_add(l3, "L3")
    try_add(l4, "L4")

    # memory（低相关先裁：已排序，逐条尝试）
    mem_texts = []
    used_mem = []
    if retrieved and retrieved.get("items"):
        for it in retrieved["items"]:
            m = it["memory"]
            line = f"- 记忆：{m.get('content','')}"
            if it.get("conflict_sibling_id"):
                line += "（存在矛盾记忆）"
            tok = _est(line)
            if tok <= remaining:
                mem_texts.append(line)
                remaining -= tok
                used_mem.append(m["id"])
    if mem_texts:
        parts.append("【相关记忆】\n" + "\n".join(mem_texts))

    # session recent（从旧到新裁，保最近）
    sess_used = False
    if session_recent:
        lines = [f"{h['role']}: {h['content']}" for h in session_recent]
        kept = []
        for ln in reversed(lines):  # 从最新往前装
            tok = _est(ln)
            if tok <= remaining:
                kept.insert(0, ln)
                remaining -= tok
        if kept:
            parts.append("【近期对话】\n" + "\n".join(kept))
            sess_used = True

    system_text = must_keep + ("\n\n" + "\n\n".join(parts) if parts else "")
    user_text = user_message
    return {
        "system_text": system_text,
        "user_text": user_text,
        "used": {"persona_claims": sorted(set(used_claims)), "memory_items": used_mem,
                 "session_context_used": sess_used},
    }
