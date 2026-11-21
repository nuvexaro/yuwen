#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 5.9-B / F5-f Phase 2：Long-term Correction Projection（Option A）。

把 persona_memory.corrections[] 中已确认(active)的 memory-domain correction，
只读、transient 投影成 retrieval/support 可消费的 active memory 视图条目。

纪律：
  - 不修改 frozen persona_memory（deepcopy；投影是瞬态视图）。
  - 不复制成永久 ordinary memory item；不产生持久 duplicate。
  - 只投影：status=active 且 target_kind=memory_item 且 corrected_value 非空的 correction。
  - 不投影：superseded / rejected / pending / expired；persona_claim / candidate correction（persona 不进 memory lane）。
  - 不 double-current：旧 target 已被 builder 标 superseded；投影的新条目是唯一 active。
  - 不改 correction_conflicts.py / F5-d / memory_retrieval / reality_boundary / builder。
  - 本模块提供纯函数；**不接线 persona_runtime.respond()**（F5-d frozen surface）。
"""

from __future__ import annotations

import copy
from typing import List, Optional

try:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
    from persona_memory_builder import memory_item_id as _memory_item_id
except Exception:  # noqa: BLE001
    _memory_item_id = None

_MEMORY_BUCKETS = ["core_facts", "timeline", "shared_experiences", "conflicts",
                   "happy_memories", "breakup", "inside_jokes", "preferences", "daily_patterns"]


def _bucket_of_target_path(target_path: Optional[str]) -> Optional[str]:
    if not target_path:
        return None
    if target_path.startswith("memory."):
        b = target_path[len("memory."):]
        return b if b in _MEMORY_BUCKETS else None
    return None


def _find_bucket_of_memory_id(persona_memory: dict, target_id: str) -> Optional[str]:
    """扫描 memory 桶定位 target_id 所在 bucket（同 builder apply_corrections 的定位方式）。"""
    for b in _MEMORY_BUCKETS:
        for it in persona_memory.get("memory", {}).get(b, []) or []:
            if it.get("id") == target_id:
                return b
    return None


def project_active_corrections(persona_memory: dict) -> dict:
    """返回 deepcopy persona_memory + 注入 active memory-correction 的 transient 投影条目。

    输入/输出均为 persona_memory dict；返回的是 deepcopy（frozen 输入绝不被修改）。
    每条 active memory correction 在目标 bucket 生成一个 active 条目（content=corrected_value），
    带 basis=correction / source_type=correction / corrected=True 与完整 provenance。
    """
    view = copy.deepcopy(persona_memory)
    corrections = view.get("corrections") or []
    mem = view.setdefault("memory", {})
    for corr in corrections:
        if corr.get("status") != "active":
            continue
        if corr.get("target_kind") != "memory_item":
            continue  # persona_claim / candidate 不进 memory lane
        cv = corr.get("corrected_value")
        if not cv:
            continue  # 纯作废类 correction（无新值）不投影
        # 解析 bucket：优先 target_path，否则按 target_id 定位（找不到则跳过，不猜）
        bucket = _bucket_of_target_path(corr.get("target_path"))
        if bucket is None:
            bucket = _find_bucket_of_memory_id(view, corr.get("target_id")) if corr.get("target_id") else None
        if bucket is None:
            continue
        # 确定性 id：复用 memory_item_id(bucket, cv)（与 builder 同规则，可 dedup）
        nid = None
        if _memory_item_id is not None:
            nid = _memory_item_id(bucket, cv)
        if not nid:
            continue
        # 已投影过（同 bucket+同 cv）→ 不重复
        bucket_list = mem.setdefault(bucket, [])
        if any(it.get("id") == nid for it in bucket_list):
            continue
        bucket_list.append({
            "id": nid,
            "content": cv,
            "importance": 1,
            "confidence": 0.5,          # 不因 projection 升高；与 F5-d 一致
            "source_type": "correction",
            "source_ref": corr.get("user_statement"),
            "status": "active",
            "corrected": True,
            "evidence_ids": [],
            "conflicts_with": [],
            "history": None,
            "valid_period": None,
            # 项目自定义 provenance（非 schema 必需，供渲染/审计）
            "basis": "correction",
            "source": "user_correction",
            "target_id": corr.get("target_id"),
            "correction_id": corr.get("id"),
            "user_statement": corr.get("user_statement"),
            "original_value": corr.get("original_value"),
            "created_at": corr.get("created_at"),
        })
    return view


def active_projection_count(persona_memory: dict) -> int:
    """统计会被投影的 active memory-correction 条数（不含已 superseded/rejected/pending/expired/persona）。"""
    n = 0
    for corr in persona_memory.get("corrections") or []:
        if corr.get("status") == "active" and corr.get("target_kind") == "memory_item" \
                and corr.get("corrected_value"):
            n += 1
    return n
