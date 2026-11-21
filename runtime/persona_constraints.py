#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Persona Constraints Renderer：把 persona_memory v1.2 五层渲染成"分区系统指令"。

优先级分层：
  L0 / Reality Boundary（最高，不可裁剪）
  L1 identity
  L2 speech_style
  L3 emotional (+sensitive topics 优先保护)
  L4 relationship
输出按层划分的字符串块；Context Assembly 决定裁哪些。deterministic。
"""

from __future__ import annotations

from typing import Dict, List

# 通用护栏（运行时常量，非冻结 schema；与 persona L0 专属合并）
GENERAL_GUARDRAILS = [
    "你不是 AI 助手，是正在扮演的{name}。但任何时候不得自称能联系真实世界中的对方。",
    "不突然变得完美或无条件包容；保持这个人的棱角。",
    "不要捏造没有依据的记忆、地点、时间或事件。",
    "被问到不想答的，可以回避、转移、或不答，不要编。",
    "不主动替用户联系/查找真实的对方。",
]


def _iter_claims(obj, path=""):
    """深度遍历 persona 里的 claim dict。"""
    if isinstance(obj, dict):
        if isinstance(obj.get("claim_id"), str) and "value" in obj:
            yield path, obj
        for k, v in obj.items():
            if k.startswith("_"):
                continue
            yield from _iter_claims(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_claims(v, path)


def collect_layers(persona_memory: dict) -> Dict[str, List[dict]]:
    """按 L0..L4 收集 claim（去掉 evidence/confidence 元数据只留 value+basis）。"""
    persona = persona_memory.get("persona", {})
    layers = {"L0": [], "L1": [], "L2": [], "L3": [], "L4": []}
    # L0
    l0 = persona.get("layer0_rules", {}) or {}
    for field in ("do_not_say", "specific_edges"):
        arr = l0.get(field) or []
        for c in arr:
            if isinstance(c, dict):
                layers["L0"].append({"field": f"layer0.{field}", "value": c.get("value"),
                                     "basis": c.get("basis")})
    rb = l0.get("reality_boundary")
    if isinstance(rb, dict):
        layers["L0"].append({"field": "layer0.reality_boundary", "value": rb.get("value"),
                             "basis": rb.get("basis")})
    # L1 identity
    for path, c in _iter_claims(persona.get("identity", {})):
        layers["L1"].append({"field": path, "value": c.get("value"), "basis": c.get("basis")})
    # L2 speech_style
    for path, c in _iter_claims(persona.get("speech_style", {})):
        layers["L2"].append({"field": path, "value": c.get("value"), "basis": c.get("basis")})
    # L3 emotional（区分 sensitive）
    for path, c in _iter_claims(persona.get("emotional_pattern", {})):
        layers["L3"].append({"field": path, "value": c.get("value"), "basis": c.get("basis")})
    # L4 relationship
    for path, c in _iter_claims(persona.get("relationship_behavior", {})):
        layers["L4"].append({"field": path, "value": c.get("value"), "basis": c.get("basis")})
    return layers


def render_system_block(persona_memory: dict, name: str, reality_flags: dict = None,
                        session_overlay: List[dict] = None) -> Dict[str, str]:
    """渲染分区系统块。返回 {guardrail, L0, L1, L2, L3, L4} 字符串，供 assembly。

    session_overlay（Stage 5.9-B F5-c）：本 session 的 correction overlay，作为
    must-keep【用户纠正】块渲染进 guardrail，使纠正事实在后续轮生效（非仅原文回显）。
    """
    layers = collect_layers(persona_memory)
    reality_flags = reality_flags or {}
    guard = "\n".join(g.replace("{name}", name) for g in GENERAL_GUARDRAILS)
    if reality_flags.get("reality_conflict"):
        guard += f"\n[现实边界提醒] {reality_flags.get('note', '')} 若无法核实，直接说“我不确定/记不清”。"
    # Stage 5.9-A3 (F2)：unsupported/insufficient 护栏由 F1 的 boundary_guard 注入
    bg = reality_flags.get("boundary_guard")
    if bg:
        guard += f"\n[现实边界提醒] {bg}"
    # Stage 5.9-B (F5-c)：session correction overlay → must-keep【用户纠正】块
    # 语义边界（2026-09-04 优化）：这是用户对 TA 属性的最新有效纠正，不是对 AI 自身
    # 人格的改写，也不是“无条件相信用户”。只对本次明确纠正的属性生效；涉及同一属性时
    # 应优先按纠正后的信息自然作答，不机械回指“你刚说…”，也不表现成顺从式“你说啥是啥”。
    if session_overlay:
        ov_lines = []
        for ov in session_overlay:
            cv = ov.get("corrected_value")
            if not cv:
                continue
            is_persona_self = ov.get("target_domain") == "persona"
            if is_persona_self:
                ov_lines.append(f"- 关于你自己的（{cv}）：这是用户刚刚纠正、关于你的当前有效说法。")
            else:
                ov_lines.append(f"- 关于 TA / 这段关系的（{cv}）：这是用户刚刚明确纠正、当前有效的信息。")
        if ov_lines:
            block = ("【已确认信息】\n"
                     "以下是用户刚刚明确纠正过的信息，是关于 TA / 这段关系（或你自身，见条目）的"
                     "当前有效事实。\n"
                     + "\n".join(ov_lines) +
                     "\n要求：涉及同一属性时，自然按这条最新信息作答，像自己一直记得一样；"
                     "不要机械复述“你刚才说……”，不要表现成无条件服从用户（如“你说啥是啥”）。"
                     "仅该条目对应的属性按纠正后的信息处理，不要扩展成相信用户说的每一句话。"
                     "若之后用户又给出与之冲突的新信息，当作新变化正常应对，而不是永久锁死本条。")
            # 提升到 guardrail 最前（must-keep 且最高优先，避免被后续现实边界/聊天稀释）
            guard = block + "\n" + guard

    def fmt(prefix, items):
        if not items:
            return ""
        lines = []
        for it in items:
            v = it.get("value")
            if v is None:
                continue
            if it.get("basis") == "correction":
                lines.append(f"- {v}（用户已纠正，务必遵守）")
            elif it.get("basis") == "direct_quote":
                lines.append(f"- {v}（ta的原话/直接行为）")
            else:
                lines.append(f"- {v}")
        return ("\n".join(lines)) if lines else ""

    blk = {
        "guardrail": guard,
        "L0": fmt("L0", layers["L0"]),
        "L1": fmt("L1", layers["L1"]),
        "L2": fmt("L2", layers["L2"]),
        "L3": fmt("L3", layers["L3"]),
        "L4": fmt("L4", layers["L4"]),
    }
    return blk
