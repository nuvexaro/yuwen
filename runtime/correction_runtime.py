#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Correction Runtime：用户纠正 → correction candidate → 本 session 立即生效 overlay。

不修改旧 evidence；不破坏 5.5 P1-A claim ID 规则——corrected value 产生自己的
确定性 claim_id（复用 persona_memory_builder.claim_id 语义，只 import 不修改冻结模块）。
只影响本 session 的解释层；跨 session 持久需走异步 rebuild / 顶层 corrections。
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

# 复用冻结 builder 的 claim_id / memory_item_id 规则（不修改它）
try:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
    from persona_memory_builder import claim_id as _pm_claim_id
    from persona_memory_builder import memory_item_id as _pm_memory_item_id
except Exception:
    _pm_claim_id = None
    _pm_memory_item_id = None


class CorrectionCandidate:
    def __init__(self, *, target_claim_id: Optional[str], user_statement: str,
                 corrected_value: Optional[str], target_hint: Optional[str] = None):
        self.target_claim_id = target_claim_id
        self.user_statement = user_statement
        self.corrected_value = corrected_value
        self.target_hint = target_hint

    def to_dict(self):
        return {"target_claim_id": self.target_claim_id, "user_statement": self.user_statement,
                "corrected_value": self.corrected_value, "target_hint": self.target_hint}


def detect_correction(user_message: str) -> bool:
    return bool(re.search(r"(不是|不对|其实(是|不)|别这么说|你记错|才不是|并不会|没这回事)", user_message))


def extract_corrected_value(user_message: str) -> Optional[str]:
    """启发式：尝试抽“其实是X”“不是X，是Y”。确定性，找不到回 None。"""
    m = re.search(r"其实是?([^。！？.!?]{1,40})", user_message)
    if m:
        return m.group(1).strip()
    m2 = re.search(r"(?:不是|不对)[^。！？.!?]{0,6}[，,、]?\s*([^。！？.!?]{1,40})", user_message)
    if m2:
        cand = m2.group(1).strip()
        if cand and not cand.startswith("不"):
            return cand
    return None


def apply_correction_to_claims(layers_value_ctx: Dict[str, list], candidate: CorrectionCandidate,
                               persona_memory: dict) -> Dict:
    """在 persona 五层 claim 上做 overlay：命中 target claim → corrected value 生成新 claim_id。

    返回 {applied: bool, new_claim_id: str|None, old_claim_id: str|None}。
    纯读冻结 persona_memory 的结构；真正的持久写入交由 session overlay / async rebuild。
    """
    # 定位 target：优先 claim_id 精确，否则按 value 近似
    target_id = candidate.target_claim_id
    if target_id is None:
        return {"applied": False, "new_claim_id": None, "old_claim_id": None,
                "reason": "无目标 claim id"}
    new_cv = candidate.corrected_value
    if new_cv is None:
        return {"applied": False, "new_claim_id": None, "old_claim_id": None,
                "reason": "无 corrected value"}
    if _pm_claim_id is None:
        return {"applied": False, "new_claim_id": None, "old_claim_id": None,
                "reason": "claim_id 不可用"}
    # 找到 target 所在 field（L0..L4）
    field = _find_field_of_claim(persona_memory, target_id)
    if field is None:
        return {"applied": False, "new_claim_id": None, "old_claim_id": None,
                "reason": "target claim 不在 persona"}
    new_id = _pm_claim_id(field, new_cv)
    return {"applied": True, "new_claim_id": new_id, "old_claim_id": target_id,
            "field": field}


# =================================================================================
# Stage 5.9-B (F5-b): 确定性 correction target resolution
# 目标：把"纠正句"映射到正确的 domain/claim/memory，而不是 speech_style 第一个 claim。
# 纪律：target unresolved → 绝不乱选已有 claim。
# =================================================================================

# 第三人称指示：指向"关于 TA 的 memory"域
_THIRD_PERSON = re.compile(r"(她|他|TA|ta|那个人|那个谁|你那个|你那位)")
# 第一人称/自指：可能指向 persona 域（说话风格/性格）或"我们"关系/共同事件
_FIRST_PERSON = re.compile(r"(我|咱|我们|咱俩|你(说|觉得)我)")
# 说话风格特征词（→ persona.speech_style）
_SPEECH_STYLE_WORDS = re.compile(r"(说话|话痨|话多|话少|爱笑|口头禅|语气|不爱说话|爱说|爱讲|沉默|寡言|爱骂|爱抱怨|能说|能聊|健谈|爱聊)")
# “话 + 程度词 + 量词”变体：话很少 / 话不多 / 特别话多 / 挺话痨
_SPEECH_AMOUNT = re.compile(r"话[很特挺真特别不怎]{0,3}(少|多|密|痨|唠)")
# 性格/情绪特征词（→ persona.emotional_pattern 或 memory 视主体）
_PERSONALITY_WORDS = re.compile(r"(性格|内|外向|开朗|内向|闷|活泼|黏人|独立|强势|温柔|暴躁|敏感|大大咧咧|小气|大方)")
# 关系/分手/感情（→ memory.relationship/shared）
_RELATIONSHIP_WORDS = re.compile(r"(分手|复合|在一起|前任|离婚|结婚|在一起过|关系|还爱|放不下)")
# 共同经历/地点/事件（→ memory.shared_experiences/timeline）
_SHARED_WORDS = re.compile(r"(去过|那次|去了|一起去|外滩|上海|北京|旅游|吃了|见面|认识)")


def _find_persona_claim_by_value(persona: dict, keywords) -> Optional[str]:
    """在 persona 各层找 value 命中任一关键词的 claim_id；找不到返回 None。"""
    def walk(obj):
        if isinstance(obj, dict):
            if isinstance(obj.get("claim_id"), str) and obj.get("value"):
                v = str(obj["value"])
                if keywords.search(v):
                    return obj["claim_id"]
            for val in obj.values():
                r = walk(val)
                if r:
                    return r
        elif isinstance(obj, list):
            for v in obj:
                r = walk(v)
                if r:
                    return r
        return None
    return walk(persona)


# ---- Stage 5.9-B (F5-b reopen, Phase 3A)：correction-over-correction target anchoring ----
# 当 memory-domain correction 无 active memory content match 时，若存在唯一、合法、同 semantic
# lane（同 field）的 active correction，让新 correction 继承该 correction 的 target_id，
# 使 F5-e lane_key(new) == lane_key(existing)，从而 F5-d/F5-e 能正确 supersede。
# 规则（只验证 domain/kind/field/target_id/status/唯一性，不做 content 猜测）：
#   - 仅 status=active & target_kind=memory_item & 同 field & 有 target_id 的 corrections[] 候选；
#   - 唯一 target_id → 继承；多个不同 target_id → ambiguous(unresolved，宁可 None 不猜错)；
#   - 零 → 不继承（调用方维持 new_memory_item/None）。
# superseded/rejected/expired/persona/assertion 天然被 status/target_kind/field 过滤。


def _field_to_bucket(field: Optional[str]) -> Optional[str]:
    if not field:
        return None
    if field.startswith("memory."):
        return _MEMORY_BUCKET_ALIAS.get(field)
    if field in _MEMORY_BUCKET_ALIAS.values():
        return field
    return None


def _inherit_active_correction_target(persona_memory: dict, field: Optional[str]) -> dict:
    """在 corrections[] 中找同 field 的唯一 active memory_item correction，返回其 target_id。

    返回 {"inherited": bool, "target_id": str|None, "ambiguous": bool}。
    ambiguous=True 表示存在多个不同 target 的候选（调用方应 unresolved，不猜）。
    """
    bucket = _field_to_bucket(field)
    if bucket is None:
        return {"inherited": False, "target_id": None, "ambiguous": False}
    cand_targets = set()
    for c in persona_memory.get("corrections") or []:
        if c.get("status") != "active":
            continue
        if c.get("target_kind") != "memory_item":
            continue
        tp = c.get("target_path")
        c_bucket = _field_to_bucket(tp) if isinstance(tp, str) else None
        if c_bucket != bucket:
            continue
        tid = c.get("target_id")
        if not tid:
            continue  # 无锚定原 memory 的 correction 不是合法语义锚
        cand_targets.add(tid)
    if len(cand_targets) == 1:
        return {"inherited": True, "target_id": next(iter(cand_targets)), "ambiguous": False}
    if len(cand_targets) > 1:
        return {"inherited": False, "target_id": None, "ambiguous": True}
    return {"inherited": False, "target_id": None, "ambiguous": False}


def _maybe_anchor(persona_memory: dict, field: str, kind: str, new_reason: str,
                  domain: str = "memory") -> dict:
    """memory-domain fall-through 的统一锚定尝试：能继承则返回 memory_item 命中，ambiguous 返回 unresolved，否则维持 new。

    domain 默认 memory；shared_memory/relationship_memory 由其 field 解析 bucket 后仍以原 domain 返回。
    """
    inh = _inherit_active_correction_target(persona_memory, field)
    if inh.get("inherited"):
        return {"ok": True, "domain": domain, "target_kind": "memory_item",
                "target_id": inh["target_id"], "field": field,
                "reason": "inherited target from existing active correction (same lane)"}
    if inh.get("ambiguous"):
        return {"ok": False, "domain": "unresolved", "target_kind": None,
                "target_id": None, "field": None,
                "reason": "multiple active correction candidates in lane; ambiguous, refuse to guess"}
    return {"ok": True, "domain": domain, "target_kind": kind,
            "target_id": None, "field": field, "reason": new_reason}


def resolve_correction_target(persona_memory: dict, user_message: str) -> dict:
    """确定纠正的目标域与目标项（不含 corrected_value 的归一化）。

    返回 {ok, domain, target_kind, target_id, field, reason, new_value_hint}
      domain ∈ persona | memory | relationship_memory | shared_memory | unresolved
      - 能确定域且域内命中 → ok=True, target_id=该项
      - 能确定域但无匹配 → ok=True, target_id=None, domain 明确（调用方新建）
      - 无法确定 → ok=False, domain=unresolved（绝不乱选已有 claim）
    """
    t = user_message.strip()
    corrected_value = extract_corrected_value(t)
    hint = corrected_value or ""
    is_third = bool(_THIRD_PERSON.search(t))
    is_first = bool(_FIRST_PERSON.search(t))
    has_speech = bool(_SPEECH_STYLE_WORDS.search(t + hint)
                      or _SPEECH_AMOUNT.search(t + hint))
    has_personality = bool(_PERSONALITY_WORDS.search(t + hint))
    has_rel = bool(_RELATIONSHIP_WORDS.search(t + hint))
    has_shared = bool(_SHARED_WORDS.search(t + hint))
    persona = persona_memory.get("persona", {})

    # 1) 第三人称 + 属性 → memory 域（关于 TA 的事实，绝不到 persona.speech_style）
    if is_third and not is_first:
        if has_speech or has_personality:
            # 性格/话痨 → core_facts（关于她/TA）；找已有 core_fact 值含该关键词
            for m in (persona_memory.get("memory", {}).get("core_facts") or []):
                if m.get("status") != "superseded" and (
                        _SPEECH_STYLE_WORDS.search(m.get("content", ""))
                        or _PERSONALITY_WORDS.search(m.get("content", ""))):
                    return {"ok": True, "domain": "memory", "target_kind": "memory_item",
                            "target_id": m["id"], "field": "memory.core_facts",
                            "reason": "third-person trait → existing core_fact"}
            # 偏好 → preferences
            for m in (persona_memory.get("memory", {}).get("preferences") or []):
                if m.get("status") != "superseded":
                    return {"ok": True, "domain": "memory", "target_kind": "memory_item",
                            "target_id": m["id"], "field": "memory.preferences",
                            "reason": "third-person trait → preference item"}
            # 无匹配 → 尝试继承同 lane active correction 的 target；否则新建（core_facts）
            return _maybe_anchor(persona_memory, "memory.core_facts",
                                 "new_memory_item",
                                 "third-person trait → new core_fact (no existing match)")
        if has_rel:
            for m in (persona_memory.get("memory", {}).get("breakup") or []) + \
                     (persona_memory.get("memory", {}).get("relationship") or []):
                if m.get("status") != "superseded":
                    return {"ok": True, "domain": "memory", "target_kind": "memory_item",
                            "target_id": m["id"], "field": "memory.relationship",
                            "reason": "third-person relationship → memory item"}
            return _maybe_anchor(persona_memory, "memory.relationship",
                                 "new_memory_item",
                                 "third-person relationship → new memory item")
        # 第三人称但无明确属性/关系 → unresolved（不硬猜）
        return {"ok": False, "domain": "unresolved", "target_kind": None,
                "target_id": None, "field": None, "reason": "third-person but no trait/rel keyword"}

    # 2) 第一人称 / 自指
    if is_first or (not is_third and has_speech and not has_shared):
        if has_speech or has_personality:
            # 说话风格 → persona.speech_style
            cid = _find_persona_claim_by_value(persona, _SPEECH_STYLE_WORDS)
            if cid:
                return {"ok": True, "domain": "persona", "target_kind": "persona_claim",
                        "target_id": cid, "field": "persona.speech_style",
                        "reason": "first-person speech style → persona claim"}
            # 性格/情绪 → persona.emotional_pattern
            cid = _find_persona_claim_by_value(persona, _PERSONALITY_WORDS)
            if cid:
                return {"ok": True, "domain": "persona", "target_kind": "persona_claim",
                        "target_id": cid, "field": "persona.emotional_pattern",
                        "reason": "first-person personality → persona claim"}
            # persona 无匹配 → 自指风格，domain 仍 persona.speech_style（新建或 overlay 到 L2 顶部）
            return {"ok": True, "domain": "persona", "target_kind": "new_persona_claim",
                    "target_id": None, "field": "persona.speech_style",
                    "reason": "first-person speech/personality → persona (no existing claim)"}
        if has_rel:
            return _maybe_anchor(persona_memory, "memory.relationship",
                                 "new_memory_item",
                                 "first-person relationship → relationship memory",
                                 domain="relationship_memory")
    # 3) "我们/咱俩" 共同经历
    if has_shared and re.search(r"(我们|咱俩|咱们)", t):
        for bucket in ("shared_experiences", "timeline"):
            for m in (persona_memory.get("memory", {}).get(bucket) or []):
                if m.get("status") != "superseded":
                    return {"ok": True, "domain": "shared_memory", "target_kind": "memory_item",
                            "target_id": m["id"], "field": f"memory.{bucket}",
                            "reason": "we-shared → memory item"}
        return _maybe_anchor(persona_memory, "memory.shared_experiences",
                             "new_memory_item",
                             "we-shared → new memory item", domain="shared_memory")

    # 4) 无法确定域
    return {"ok": False, "domain": "unresolved", "target_kind": None,
            "target_id": None, "field": None,
            "reason": "no clear subject/domain to target"}


# =================================================================================
# Stage 5.9-B (F5-d): effective memory view projection（memory-domain correction → retrieval 可见）
# 纪律：
#   - 以 frozen persona_memory 为基座 deepcopy 出瞬态 effective view；绝不改 frozen。
#   - 仅 target_domain ∈ {memory, relationship_memory, shared_memory} 进入投影。
#   - persona-domain correction 严禁投影到 memory。
#   - 复用 F5-b 已确定的 target_domain / deterministic new_claim_id；不重新猜 domain。
#   - 投影 item 保留 basis=correction / source=user_correction / source_turn / at 等 provenance。
#   - 同属性(同 field) correction 后者 supersede 前者；无关 correction / 普通 assertion 不 supersede。
#   - 不改 confidence 语义；不把 correction 自动提成普通高置信记忆。
# =================================================================================

# 运行时 persona_memory.memory 固定 9 桶（schema 亦同）。resolver 的 field 需映射到真实 bucket。
_MEMORY_BUCKET_ALIAS = {
    "memory.core_facts": "core_facts",
    "memory.preferences": "preferences",
    "memory.relationship": "breakup",        # schema/runtime 无独立 relationship 桶；关系载体为 breakup
    "memory.shared_experiences": "shared_experiences",
    "memory.timeline": "timeline",
    "memory.conflicts": "conflicts",
    "memory.happy_memories": "happy_memories",
    "memory.breakup": "breakup",
    "memory.inside_jokes": "inside_jokes",
    "memory.daily_patterns": "daily_patterns",
}

# 可投影到 memory 的 target_domain（persona 严禁进入）
_PROJECTABLE_DOMAINS = {"memory", "relationship_memory", "shared_memory"}


def _bucket_of_field(field: Optional[str]) -> Optional[str]:
    if not field:
        return None
    if field.startswith("memory."):
        return _MEMORY_BUCKET_ALIAS.get(field)
    # 容错：已是裸 bucket 名
    if field in _MEMORY_BUCKET_ALIAS.values():
        return field
    return None


def effective_memory_view(frozen_persona_memory: dict, session_overlay: list) -> dict:
    """从 frozen persona_memory 生成瞬态 effective view（deepcopy），注入 memory-domain correction。

    返回 deepcopy 后的 persona_memory；frozen 输入绝不修改。
    同属性(同 bucket+同 target_id/同语义) 的后序 correction 会 supersede 前序投影项。
    """
    import copy as _copy
    view = _copy.deepcopy(frozen_persona_memory)
    overlay = session_overlay or []
    if not overlay:
        return view
    mem = view.setdefault("memory", {})
    # 按 (bucket, target_id) 聚合，仅保留同属性 correction 的"最新一条"为 current。
    # 投影项原生 bucket 归属：字段 field 决定 bucket（relationship → breakup）。
    # 分组 key：优先 target_id（若命中已有项），否则 field。
    projected = []  # (field, bucket, target_id, ov)
    for ov in overlay:
        domain = ov.get("target_domain")
        if domain not in _PROJECTABLE_DOMAINS:
            continue  # persona / unresolved 严禁进 memory
        bucket = _bucket_of_field(ov.get("field"))
        if not bucket:
            # 无有效 field 但 domain 可投影 → 缺 bucket，跳过（不猜测）
            continue
        projected.append((ov.get("field"), bucket, ov.get("target_id"), ov))

    # 分组：同 (bucket, target_id) 视为同属性；无 target_id 时按 field 聚合，保最新
    groups = {}
    order = []
    for (field, bucket, target_id, ov) in projected:
        key = (bucket, target_id)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(ov)
    for key in order:
        ovs = groups[key]
        latest = ovs[-1]  # append 序 = 时间序（correction 按轮 append）
        older = ovs[:-1]
        bucket = key[0]
        target_id = key[1]
        content = latest.get("corrected_value")
        new_id = latest.get("new_claim_id")
        if not content or not new_id:
            continue
        item = {
            "id": new_id,
            "content": content,
            "importance": 1,
            "confidence": 0.5,             # correction 默认中等；不因投影自动升高
            "source_type": "correction",
            "source_ref": latest.get("source_turn"),
            "status": "active",
            "corrected": True,
            "evidence_ids": [],
            "conflicts_with": [],
            "history": None,
            "valid_period": None,
            "basis": "correction",          # 项目自定义 provenance（非 schema 必需）
            "source": "user_correction",    # 项目自定义 provenance
            "source_turn": latest.get("source_turn"),
            "at": latest.get("at"),
            "field": latest.get("field"),
        }
        bucket_list = mem.setdefault(bucket, [])
        # 移除同 bucket 同 target_id 的旧投影项（superseded 语义：前一个 correction 保留 provenance 但不再 current）
        keep = []
        for existing in bucket_list:
            if target_id is not None and existing.get("id") == target_id:
                # 命中真实 memory item → 不改它（frozen 只读视图）；把新 correction 作为并列项
                keep.append(existing)
            elif existing.get("source") == "user_correction" and existing.get("id") in {o.get("new_claim_id") for o in ovs[:-1]}:
                # 旧 correction 投影项 → 标 superseded_by，保留 provenance
                ex2 = _copy.deepcopy(existing)
                ex2["status"] = "superseded"
                ex2["supersede_kind"] = "corrected"
                ex2["superseded_by"] = new_id
                keep.append(ex2)
            else:
                keep.append(existing)
        # 追加旧 correction 的 superseded 投影（若之前没进过 bucket_list）
        for ov in ovs[:-1]:
            old_id = ov.get("new_claim_id")
            old_c = ov.get("corrected_value")
            if old_id and old_c and old_id != new_id:
                exists_old = any(e.get("id") == old_id for e in keep)
                if not exists_old:
                    keep.append({
                        "id": old_id, "content": old_c, "importance": 1, "confidence": 0.5,
                        "source_type": "correction", "source_ref": ov.get("source_turn"),
                        "status": "superseded", "supersede_kind": "corrected", "superseded_by": new_id,
                        "corrected": True, "evidence_ids": [], "conflicts_with": [],
                        "basis": "correction", "source": "user_correction",
                        "source_turn": ov.get("source_turn"), "at": ov.get("at"), "field": ov.get("field"),
                    })
        keep.append(item)
        bucket_list[:] = keep
    return view


def _find_field_of_claim(persona_memory: dict, claim_id: str) -> Optional[str]:
    from persona_constraints import collect_layers
    # collect_layers 不含 field→claim_id 映射；直接用遍历定位 field path
    persona = persona_memory.get("persona", {})

    def walk(obj, path):
        if isinstance(obj, dict):
            if isinstance(obj.get("claim_id"), str) and obj["claim_id"] == claim_id:
                return path
            for k, v in obj.items():
                if k.startswith("_"):
                    continue
                r = walk(v, f"{path}.{k}" if path else k)
                if r:
                    return r
        elif isinstance(obj, list):
            for v in obj:
                r = walk(v, path)
                if r:
                    return r
        return None
    return walk(persona, "")
