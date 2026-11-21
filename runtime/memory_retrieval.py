#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Memory Retrieval（deterministic 规则 scorer，纯函数）。

不依赖向量库；LLM 不决定 relevance。MVP 规则：
  content term overlap + temporal active bonus − conflict 惩罚，设阈值。
返回带 conflict 对手的项（若召回 active conflict 一方，同时带出对手并标 conflict）。
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

# G3-4：不得作为"当前事实"召回的 lifecycle status。
# 仅用于 retrieve() 的 selection filtering；default_scorer() 的 scoring 逻辑不引用此集合。
# 注意 pending_confirmation **不在**此集合：本仓库中它是"冲突对一方、等待裁决"
# （persona_memory_builder.py 冲突组 → pending），须保留召回以便带出 conflict sibling。
_NON_CURRENT_STATUSES = frozenset({"superseded", "rejected"})


def _terms(text: str) -> set:
    # 简单分词：中日韩单字 + 连续 ascii 词
    ascii_words = set(re.findall(r"[a-zA-Z0-9_]+", text.lower()))
    cjk = set(re.findall(r"[一-鿿]", text))
    stop = set("的了是在有和我你她他也就会把被让跟对从去来说到过那就吧吗呢啊哈嗯")
    cjk = {c for c in cjk if c not in stop}
    return ascii_words | cjk


def _mem_terms(m: dict) -> set:
    body = m.get("content", "")
    body += " " + " ".join(m.get("tags", []))
    return _terms(body)


def _active_now(m: dict, now: Optional[datetime]) -> bool:
    """按 valid_period / event_time 判定是否"当前有效"。status 已过滤 superseded/corrected。"""
    if m.get("status") == "superseded":
        return False
    vp = m.get("valid_period")
    if not vp:
        return True  # 无时间锚 → 视为可召回
    now_dt = now or datetime.now()
    fr = vp.get("from") or {}
    to = vp.get("to") or {}
    fr_v = fr.get("value")
    to_v = to.get("value")
    try:
        if fr_v and str(now_dt)[:4] < _norm_year(fr_v):
            return False
        if to_v and str(now_dt)[:4] > _norm_year(to_v):
            return False
    except Exception:
        return True
    return True


def _norm_year(v):
    return re.sub(r"[^0-9]", "", str(v))[:4] or "9999"


def default_scorer(user_message: str, memory: dict, now: Optional[datetime] = None) -> float:
    """返回 relevance 0..1。非当前有效（valid_period 未到/已过）→ 0。"""
    if memory.get("status") == "superseded":
        return 0.0
    if not _active_now(memory, now):
        return 0.0
    ut = _terms(user_message)
    mt = _mem_terms(memory)
    if not mt or not ut:
        return 0.0
    overlap = len(ut & mt)
    if overlap == 0:
        return 0.0
    base = min(1.0, overlap / min(len(ut), 3)) + 0.05  # active bonus 并入
    return round(min(1.0, base), 3)


def retrieve(persona_memory: dict, session_state: dict, user_message: str,
             k: int = 5, now: Optional[datetime] = None,
             scorer: Optional[Callable] = None,
             threshold: float = 0.2) -> dict:
    """返回 {items: [(memory, score, conflict_sibling)], used_ids: [...]}。

    规则：
    - superseded/corrected 的当前值不作为当前事实召回（evolved 历史段由调用方按"过去"召回）。
    - 召回 active conflict 一方 → 同时带出对手。
    """
    scorer = scorer or default_scorer
    memory_items = [it for bucket in persona_memory.get("memory", {}).values() for it in bucket]
    # 当前有效：排除 _NON_CURRENT_STATUSES（superseded / rejected）；
    # corrected 语义经 supersede_kind=corrected 排除
    current = [m for m in memory_items if m.get("status") not in _NON_CURRENT_STATUSES]
    # conflicts 索引
    by_id = {m["id"]: m for m in memory_items}
    scored = []
    for m in current:
        s = scorer(user_message, m, now)
        if s >= threshold:
            scored.append((m, s, None))
    scored.sort(key=lambda x: -x[1])
    picked = scored[:k]
    # conflict sibling
    result = []
    seen = set()
    for m, s, _ in picked:
        if m["id"] in seen:
            continue
        seen.add(m["id"])
        sibling_id = None
        cw = m.get("conflicts_with") or []
        # 只带仍为当前有效的对手（同样排除 _NON_CURRENT_STATUSES）
        for cid in cw:
            if cid in by_id and by_id[cid].get("status") not in _NON_CURRENT_STATUSES:
                sibling_id = cid
                break
        result.append({"memory": m, "score": s, "conflict_sibling_id": sibling_id})
        if sibling_id and sibling_id not in seen:
            seen.add(sibling_id)
    return {"items": result,
            "used_ids": [m["id"] for m in memory_items if m["id"] in seen]}
