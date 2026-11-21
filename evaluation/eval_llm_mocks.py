#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 5.6 Evaluation：确定性 mock LLM（供 extractor 链路注入）。

Golden case 从 messages.json 出发走真实冻结链路。extractor 需要 LLM——
为可重复 benchmark，提供一个确定性 mock：解析 extractor prompt 中的 <row ...>
消息行，为每条 target_message 行生成一个 basis=direct_quote 的候选。
这使 5.3–5.5（本框架主要评测对象）在固定候选流上可复现。

mock 只服务 eval；不改任何冻结模块。
"""

from __future__ import annotations

import json
import re


def _parse_rows(prompt: str):
    """从 extractor prompt 解析 <row i kind src msgid sent>…</row>。"""
    rows = []
    pat = re.compile(
        r"<row i=(\d+) kind=(\w+) src=([^ ]*) msgid=([^ ]*) sent=([^>]*)>\n(.*?)\n</row>",
        re.S)
    for m in pat.finditer(prompt):
        rows.append({
            "i": int(m.group(1)), "kind": m.group(2), "src": m.group(3),
            "msgid": m.group(4), "sent": m.group(5), "text": m.group(6).strip(),
        })
    return rows


def extractor_mock_llm(prompt: str) -> str:
    """确定性 mock：target_message 行 → direct_quote 候选（claim = 原消息文本）。"""
    rows = _parse_rows(prompt)
    cands = []
    for r in rows:
        if r["kind"] == "target_message":
            cands.append({
                "evidence_type": "target_message",
                "claim": {"value": r["text"], "basis": "direct_quote"},
                "supporting_message_ids": [r["msgid"]] if r["msgid"] else [],
                "source_refs": [r["src"]] if r["src"] else [],
                "speaker_role": "target",
                "observed_at": r["sent"] or None,
                "confidence": 0.9,
                "importance": 3,
                "source_type": "wechat_log",
            })
        elif r["kind"] == "user_narration":
            cands.append({
                "evidence_type": "user_narration",
                "claim": {"value": r["text"], "basis": "user_report_only"},
                "supporting_message_ids": [],
                "source_refs": [r["src"]] if r["src"] else ["user_narration"],
                "speaker_role": "user",
                "observed_at": None,
                "confidence": 0.6,
                "importance": 2,
                "source_type": "user_narration",
            })
    return json.dumps(cands, ensure_ascii=False)


# persona_memory_builder 的 interpreter 也用 mock（同风格确定性回退其实已内置；
# 这里提供可注入的占位，供需要 LLM persona 建议的 case 使用——默认 builder 无 LLM 即保守）。
# 本框架对 builder 用 llm=None（确定性回退：只归 memory、不臆造 persona），
# 从而 benchmark 聚焦 builder 在无外部文本漂移下的行为。
