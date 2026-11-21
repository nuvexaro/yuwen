#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 5.9-B / F5-f Phase 3B：Persona Loader（verdict-execution only，非第二语义权威）。

职责：
  long-term corrections[] (persistent correctionItem) + session overlay correction
  → [adapter] → F5-e resolve_statements() → semantic verdict（唯一语义裁决）
  → 机械执行 verdict → transient runtime base（omit F5-e 判 superseded 的 projection）
  → 现有 F5-d 在其上叠加 session overlay。

铁律：
  - F5-e 是唯一 semantic authority。本 loader 不自行判断 same_field/same_target/same_lane/
    newer/current/superseded —— 它只读 F5-e resolve_statements() 的 lanes 输出。
  - adapter 是纯字段映射（persistent correctionItem → F5-e statement），不改语义身份。
  - omit 依据：F5-e 的 lane.superseded[] 里被 supersede 的 correction（携带其 id）。
    机械定位 = 在 Phase-2 投影产物中找 correction_id 等于该 superseded correction id 的投影项，omit。
  - 不改 persona_runtime.respond() / F5-d / F5-e / memory_retrieval / reality_boundary / Phase-2 projection。
"""

from __future__ import annotations

import copy
from typing import Dict, List, Optional

import correction_conflicts as f5e
import correction_longterm_projection as phase2


def correction_item_to_statement(corr: dict) -> dict:
    """纯字段映射：persistent correctionItem → F5-e statement。不重推语义。

    correctionItem(target_path="memory.core_facts") → field。
    保持 correction_id(id)、target_id、corrected_value、user_statement、created_at。
    """
    field = corr.get("target_path")
    if not field:
        field = "memory.core_facts"
    return {
        "kind": f5e.KIND_CORRECTION,
        "value": corr.get("corrected_value"),
        "id": corr.get("id"),
        "source_turn": corr.get("user_statement"),
        "at": corr.get("created_at"),
        "target_domain": "memory",
        "field": field,
        "target_id": corr.get("target_id"),
    }


def overlay_to_statement(ov: dict) -> dict:
    """session persona_overlay entry → F5-e statement（复用 F5-e 的 build_statements_from_overlay 语义，纯映射）。"""
    return {
        "kind": f5e.KIND_CORRECTION,
        "value": ov.get("corrected_value"),
        "id": ov.get("new_claim_id"),
        "source_turn": ov.get("source_turn"),
        "at": ov.get("at"),
        "target_domain": ov.get("target_domain"),
        "field": ov.get("field"),
        "target_id": ov.get("target_id"),
    }


def load_runtime_persona(longterm_persona_memory: dict,
                         session_overlay: Optional[List[dict]] = None) -> dict:
    """构造 transient runtime base。

    步骤：
      1. Phase-2 投影 long-term active memory-corrections → 含 projection 的 base。
      2. 若存在 session overlay correction：把 persistent active memory-corrections + session overlay
         correction 都映射为 statement，交 F5-e resolve_statements()。
      3. 对每条 overlay correction，若它在某 lane 是 current，而同 lane 有被 supersede 的
         persistent correction（lane.superseded 中的 id），则从 base 中 omit correction_id 匹配的 projection。
      4. 返回 transient base（frozen PM 与 Phase-2 产物均不修改；返回 deepcopy）。

    本函数不含任何 lane/field/target/newer 自判：一切来自 F5-e lanes 输出。
    """
    base = phase2.project_active_corrections(longterm_persona_memory)
    overlay = session_overlay or []
    if not overlay:
        return base  # 无 session correction → 无 supersede 可执行，直接返回 Phase-2 base

    # 只取 memory-domain、可映射的 session overlay correction
    mem_overlay = [o for o in overlay
                   if o.get("target_domain") in ("memory", "relationship_memory", "shared_memory")
                   and o.get("corrected_value") and o.get("new_claim_id")]

    # 收集 persistent active memory corrections（仅这些是 projection 的来源）
    persistent = [c for c in (longterm_persona_memory.get("corrections") or [])
                  if c.get("status") == "active" and c.get("target_kind") == "memory_item"
                  and c.get("corrected_value")]

    # F5-e 归约：persistent + overlay corrections 统一进 resolve_statements
    stmts = [correction_item_to_statement(c) for c in persistent] + \
            [overlay_to_statement(o) for o in mem_overlay]
    lanes = f5e.resolve_statements(stmts)

    # 收集所有被 F5-e 判 superseded 的 persistent correction id
    superseded_persistent_ids: set = set()
    for lane in lanes.values():
        for s in lane.get("superseded", []):
            if s.get("kind") == "correction" and s.get("id"):
                superseded_persistent_ids.add(s["id"])

    if not superseded_persistent_ids:
        return base  # 无 superseded verdict → 无需 omit

    # 机械执行：从 base 中 omit correction_id ∈ superseded_persistent_ids 的 projection 项
    result = copy.deepcopy(base)
    for bucket, items in result.get("memory", {}).items():
        if not isinstance(items, list):
            continue
        kept = []
        for it in items:
            cid = it.get("correction_id")
            if cid in superseded_persistent_ids:
                continue  # F5-e 判 superseded 的 projection → omit（verdict execution）
            kept.append(it)
        result["memory"][bucket] = kept
    return result
