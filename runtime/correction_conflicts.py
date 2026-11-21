#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 5.9-B / F5-e：A/B/C correction 冲突语义（纯函数层，不改任何 F5-d / 现有文件）。

解决的问题：同一属性上，原值(A) / 用户纠正(B) / 后续说法(C) 三者的
  current / superseded / conflict / provenance 如何确定性判定。

铁律：
  - correction → correction：允许 supersession（新纠正 supersede 旧纠正）。
  - ordinary assertion → correction：禁止 supersession（普通断言永不覆盖纠正）。
  - assertion 不得因 append-order / 时间更晚而成为 current correction。
  - 不同 target / 不同属性（lane）互不覆盖。
  - A/B/C provenance 全部保留。
  - supersede / conflict 关系确定性；绝不以"最后一句"作为事实判定规则。

本模块是纯函数：不改 persona_memory（bytes 恒不变），不改 effective_memory_view /
respond / memory_retrieval / reality_boundary。供冲突语义判定与未来持久层引用。
"""

from __future__ import annotations

from typing import Dict, List, Optional

# statement kind
KIND_CORRECTION = "correction"
KIND_ASSERTION = "assertion"


def lane_key(stmt: dict) -> tuple:
    """属性隔离键：不同 target / 不同 field → 不同 lane，互不 supersede。"""
    return (stmt.get("target_domain"), stmt.get("field"), stmt.get("target_id"))


def _to_current(stmt: dict) -> dict:
    """把一条 statement 转成 current 项（含 provenance）。"""
    return {
        "kind": stmt.get("kind"),
        "value": stmt.get("value"),
        "id": stmt.get("id"),
        "source_turn": stmt.get("source_turn"),
        "at": stmt.get("at"),
        "target_domain": stmt.get("target_domain"),
        "field": stmt.get("field"),
        "target_id": stmt.get("target_id"),
    }


def _to_ghost(kind: str, stmt: dict) -> dict:
    """把被 supersede 的 statement 转成 superseded/conflict 历史项（provenance 保留）。"""
    g = _to_current(stmt)
    g["kind"] = kind
    return g


def resolve_statements(statements: List[dict]) -> Dict[str, dict]:
    """输入有序 statement 流（list 顺序 = 时间顺序），输出按 lane 聚合的确定性冲突状态。

    statement 字段：{kind, value, id, source_turn, at, target_domain, field, target_id}
      kind ∈ correction | assertion

    输出：{lane_key: {
        current: {...}|None,          # 当前有效（correction 优先；无 correction 时为最近 assertion）
        superseded: [...],            # 被后序 correction 取代者（含原 assertion / 旧 correction）
        conflicts: [...],             # 当有 correction 在岗时到达的普通 assertion（不 supersede）
    }}
    铁律：correction 在岗时，任何后到 assertion 永不成为 current。
    """
    lanes: Dict[tuple, dict] = {}
    for stmt in statements:
        lk = lane_key(stmt)
        lane = lanes.setdefault(lk, {"current": None, "superseded": [], "conflicts": []})
        kind = stmt.get("kind")
        if kind == KIND_CORRECTION:
            if lane["current"] is not None:
                # 现有 current（assertion 或旧 correction）→ 被新 correction supersede
                lane["superseded"].append(_to_ghost(lane["current"]["kind"], {
                    "kind": lane["current"]["kind"], "value": lane["current"]["value"],
                    "id": lane["current"]["id"], "source_turn": lane["current"].get("source_turn"),
                    "at": lane["current"].get("at"), "target_domain": lane["current"].get("target_domain"),
                    "field": lane["current"].get("field"), "target_id": lane["current"].get("target_id"),
                }))
            lane["current"] = _to_current(stmt)
        else:  # KIND_ASSERTION
            if lane["current"] is not None and lane["current"]["kind"] == KIND_CORRECTION:
                # correction 在岗：普通断言绝不 supersede → 记为 conflict
                lane["conflicts"].append(_to_ghost(KIND_ASSERTION, stmt))
            elif lane["current"] is not None:
                # 当前是普通 assertion（无 correction）→ 新 assertion supersede 旧 assertion
                lane["superseded"].append(_to_ghost(lane["current"]["kind"], {
                    "kind": lane["current"]["kind"], "value": lane["current"]["value"],
                    "id": lane["current"]["id"], "source_turn": lane["current"].get("source_turn"),
                    "at": lane["current"].get("at"), "target_domain": lane["current"].get("target_domain"),
                    "field": lane["current"].get("field"), "target_id": lane["current"].get("target_id"),
                }))
                lane["current"] = _to_current(stmt)
            else:
                lane["current"] = _to_current(stmt)
    return {str(k): v for k, v in lanes.items()}


def current_value(lanes: Dict[str, dict], target_domain: str, field: str,
                  target_id: Optional[str] = None) -> Optional[str]:
    """取某 lane 的 current value；无则 None。"""
    lk = str((target_domain, field, target_id))
    lane = lanes.get(lk)
    if not lane or lane["current"] is None:
        return None
    return lane["current"]["value"]


def build_statements_from_overlay(overlay: List[dict]) -> List[dict]:
    """把 persona_overlay 里的 correction 条目转成 statement 流（correction kind）。

    overlay 条目字段（F5-d/F5-c 已产出）：{target_domain, corrected_value, new_claim_id,
      field, source_turn, at, target_id}。
    只取可投影域（memory / relationship_memory / shared_memory）与 persona（按需），
    保持与 F5-d 一致的确定性 id。persona-overlay 保留（供 persona 冲突语义用），
    但绝不进 memory lane。
    """
    out = []
    for ov in overlay or []:
        value = ov.get("corrected_value")
        if not value:
            continue
        domain = ov.get("target_domain")
        field = ov.get("field")
        if field is None:
            continue
        out.append({
            "kind": KIND_CORRECTION,
            "value": value,
            "id": ov.get("new_claim_id") or ov.get("corrected_value"),
            "source_turn": ov.get("source_turn"),
            "at": ov.get("at"),
            "target_domain": domain,
            "field": field,
            "target_id": ov.get("target_id"),
        })
    return out
