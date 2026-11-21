#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 5.9-B / F5-f Phase 1：Persistence Export（correction-proposal 导出层）。

把 Session.persona_overlay 中已确立的 correction，经 F5-e resolve_statements() 语义归约后，
导出为 correction-proposal（pending → confirmation → active correction input）。

纪律（本文件只读 persona_memory / 不改 frozen）：
  - correction 语义只能由 F5-e resolve_statements() 裁决；本层只做"导出/过滤/聚合"。
  - 普通 assertion 不得进入 correction-proposal / corrections[]。
  - pending / rejected / expired 不得进入长期 build 输入。
  - session isolation：proposal 带 source_session_id；导出只针对指定 session。
  - provenance 保留；deterministic identity 保持（沿用 overlay 的 new_claim_id）。
  - 不改 correction_conflicts.py / F5-d / frozen builder / memory_retrieval / reality_boundary。
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

import correction_conflicts as f5e

# proposal 生命周期
PROPOSAL_PENDING = "pending"
PROPOSAL_CONFIRMED = "confirmed"     # = active correction input（可进 5.5）
PROPOSAL_REJECTED = "rejected"
PROPOSAL_EXPIRED = "expired"

# 允许进入长期 persistence 的 target_domain（memory 域；persona 由另一机制，本 Phase 不处理）
_EXPORTABLE_DOMAINS = {"memory", "relationship_memory", "shared_memory"}


def _build_proposal(ov: dict, status: str, source_session_id: str) -> dict:
    """从单条 overlay correction 构建 proposal（deterministic id = overlay 的 new_claim_id）。"""
    return {
        "proposal_id": "cp_" + (ov.get("new_claim_id") or "").lstrip("mi_")[:12]
                       if ov.get("new_claim_id") else None,
        "kind": "correction",
        "target_kind": "memory_item",
        "target_domain": ov.get("target_domain"),
        "target_id": ov.get("target_id"),
        "field": ov.get("field"),
        "original_value": ov.get("old_value"),
        "corrected_value": ov.get("corrected_value"),
        "new_claim_id": ov.get("new_claim_id"),
        "user_statement": ov.get("source_turn"),
        "source": "session_correction",
        "source_session_id": source_session_id,
        "status": status,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "provenance": {
            "source_turn": ov.get("source_turn"),
            "at": ov.get("at"),
            "target_domain": ov.get("target_domain"),
            "field": ov.get("field"),
            "target_id": ov.get("target_id"),
        },
    }


def export_correction_proposals(persona_overlay: List[dict], *,
                                existing_proposals: Optional[List[dict]] = None,
                                source_session_id: str = "default") -> Dict[str, list]:
    """F5-f Phase 1 核心：归约 session overlay 并导出 proposal。

    流程：
      1. 仅取可导出域（memory-domain）overlay 条目；
      2. 用 F5-e build_statements_from_overlay + resolve_statements 做语义归约，
         得到每 lane 的 current correction（active 候选）与 superseded（历史，不导出为 active）；
      3. 对照 existing_proposals（pending/confirmed/rejected/expired）决定新 proposal 状态：
         - 全新 lane current correction → status=pending（新候选，待确认）；
         - 已存在同 new_claim_id 的 proposal → 保持其既有状态（不重复、不覆盖用户裁决）；
      4. 返回 {proposals:[...], active_correction_input:[...], superseded:[...]}。

    active_correction_input = 归约后、status=confirmed 的 correction（可进 5.5 corrections 参数）。
    pending 永不进 active_correction_input。rejected/expired 永不被重新激活。
    """
    # 1) 只取可导出域的 overlay
    exportable = [ov for ov in (persona_overlay or [])
                  if ov.get("target_domain") in _EXPORTABLE_DOMAINS
                  and ov.get("corrected_value")]
    # 2) F5-e 语义归约
    stmts = f5e.build_statements_from_overlay(exportable)
    lanes = f5e.resolve_statements(stmts)
    # 聚合 lane current 为 "待导出 corrections"，用其 deterministic id 去重
    by_id: Dict[str, dict] = {}
    for lane in lanes.values():
        cur = lane.get("current")
        if cur and cur.get("kind") == "correction" and cur.get("id"):
            by_id[cur["id"]] = {
                "new_claim_id": cur["id"],
                "corrected_value": cur["value"],
                "target_domain": cur.get("target_domain"),
                "field": cur.get("field"),
                "target_id": cur.get("target_id"),
                "old_value": None,
                "source_turn": cur.get("source_turn"),
                "at": cur.get("at"),
            }

    existing = {p.get("new_claim_id") or p.get("proposal_id"): p for p in (existing_proposals or [])}

    proposals: List[dict] = []
    active_input: List[dict] = []
    for nid, ov in by_id.items():
        prior = existing.get(nid)
        if prior:
            # 已存在 proposal → 保留其状态（pending 仍 pending；confirmed 进 active；rejected/expired 不复活）
            status = prior.get("status", PROPOSAL_PENDING)
        else:
            status = PROPOSAL_PENDING  # 新 correction → 待确认
        p = _build_proposal(ov, status, source_session_id)
        # 保留既有 proposal 的 id（避免每次导出换 id）
        if prior and prior.get("proposal_id"):
            p["proposal_id"] = prior["proposal_id"]
        p["status"] = status
        proposals.append(p)
        if status == PROPOSAL_CONFIRMED:
            active_input.append(p)

    # superseded corrections（供审计；不导出为 active）
    superseded: List[dict] = []
    for lane in lanes.values():
        for s in lane.get("superseded", []):
            superseded.append({"value": s.get("value"), "source_turn": s.get("source_turn"),
                               "at": s.get("at"), "kind": s.get("kind")})
    return {"proposals": proposals, "active_correction_input": active_input,
            "superseded": superseded}


def confirm_proposal(proposal: dict) -> dict:
    """pending → confirmed（active correction input）。用户/系统确认后调用。"""
    proposal["status"] = PROPOSAL_CONFIRMED
    return proposal


def reject_proposal(proposal: dict) -> dict:
    """pending/confirmed → rejected（永不复活）。"""
    proposal["status"] = PROPOSAL_REJECTED
    return proposal


def expire_proposal(proposal: dict) -> dict:
    """pending → expired（永不复活）。"""
    proposal["status"] = PROPOSAL_EXPIRED
    return proposal


def filter_active_for_build(proposals: List[dict]) -> List[dict]:
    """供 5.5 corrections 参数：只收 confirmed（active），pending/rejected/expired 一律排除。"""
    return [p for p in proposals if p.get("status") == PROPOSAL_CONFIRMED]
