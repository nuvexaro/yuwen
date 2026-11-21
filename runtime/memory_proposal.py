#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Memory Proposal：用户陈述 → proposal（候选，不入长期 Persona/Memory）。

LLM 输出 / 人格台词绝不直接进 proposal 的"事实"通道。proposal 需后续
用户确认/导入 → 5.2→5.5 才进长期记忆。此模块只生成候选并维护队列。
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import List, Optional


_GREETING = ("在干嘛", "你好", "嗨", "哈喽", "早", "晚安", "吃了没", "干嘛呢",
             "在吗", "hello", "hi")


def is_user_new_fact_statement(user_message: str, user_category: str) -> bool:
    """用户陈述句且像"新事实"才可能成 proposal。question/guess/correction 不算。"""
    if user_category in ("question", "guess", "correction"):
        return False
    t = user_message.strip()
    if not t:
        return False
    if len(t) < 6:
        return False
    if any(g in t for g in _GREETING):
        return False
    # 情绪即时句不构成长期事实
    if re.search(r"(我今天(好|很)|我有点|我最近好|我好累|心情|感觉)", t) and len(t) < 15:
        return False
    return True


def build_proposal(user_message: str, *, source_session: str, category: str) -> Optional[dict]:
    """返回 proposal dict 或 None。deterministic。"""
    if not is_user_new_fact_statement(user_message, category):
        return None
    return {
        "proposal_id": "pr_" + uuid.uuid4().hex[:12],
        "text": user_message.strip(),
        "source": "user_session",
        "source_session": source_session,
        "kind": "session_new_fact",
        "status": "pending",          # 待确认/导入；不自动成为 persona/memory
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }


def record_proposal(session, proposal: Optional[dict]):
    if proposal:
        session.pending_confirmations.append(proposal)
