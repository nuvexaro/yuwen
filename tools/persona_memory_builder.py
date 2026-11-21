#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Persona / Memory Builder（Stage 5.5）

输入：ResolvedEvidenceBundle（5.4 冻结）+ CandidateSet（可回溯）+ optional corrections + name_or_alias
输出：persona_memory.schema v1.2 实例（校验通过才返回）

本层是把"验证过的证据"解释/构建为 Persona + Memory 的 interpretation 层。
程序权威：provenance / ID / lifecycle / dedup / conflict / correction / schema validation /
basis / speaker / evidence_type / confidence 上限 / evidence_ids。
LLM 可注入，只负责 interpretation（每组 → 建议 memory_bucket / persona_leaf + value_text），
且输出须经程序白名单校验；无 LLM 时用确定性保守回退（只归 memory，不臆造 persona）。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime
from typing import Callable, Dict, List, Optional

PM_SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "persona_memory.schema.json")
BUNDLE_SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                  "resolved_evidence_bundle.schema.json")


class BuilderError(Exception):
    pass


def _load_validator(path: str):
    import jsonschema
    from jsonschema import Draft202012Validator, FormatChecker

    def _iso(v):
        if not isinstance(v, str):
            return True
        try:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
            return True
        except ValueError:
            return False

    FormatChecker.checkers["date-time"] = (lambda i: _iso(i), ValueError)
    with open(path, encoding="utf-8") as f:
        schema = json.load(f)
    return Draft202012Validator(schema, format_checker=FormatChecker())


_pm_validator = _load_validator(PM_SCHEMA_PATH)
_bundle_validator = _load_validator(BUNDLE_SCHEMA_PATH)


def _schema_errs(v, data):
    return [f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in v.iter_errors(data)]


def _sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8", "surrogatepass")).hexdigest()


def _canonical(text: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKC", text or "")
    s = re.sub(r"\s+", "", s)
    s = "".join(ch for ch in s if ch.isalnum() or "一" <= ch <= "鿿"
                or "぀" <= ch <= "ヿ" or "가" <= ch <= "힯")
    return s.lower() or "_empty_"


# ---------------------------------------------------------------------------
# persona 叶子注册表
# ---------------------------------------------------------------------------
MEMORY_BUCKETS = ["core_facts", "timeline", "shared_experiences", "conflicts",
                  "happy_memories", "breakup", "inside_jokes", "preferences", "daily_patterns"]

# leaf 定义：card(single/array) / vtype / L0 标记 / 枚举词表
FIELDS: Dict[str, dict] = {
    # L0
    "layer0_rules.do_not_say": {"card": "array", "l0": True},
    "layer0_rules.specific_edges": {"card": "array", "l0": True},
    "layer0_rules.reality_boundary": {"card": "single", "l0": True},
    # L1 identity
    "identity.name_or_alias": {"card": "single"},
    "identity.age": {"card": "single", "int": True},
    "identity.gender": {"card": "single", "enum": ["male", "female", "unknown", "do_not_infer"]},
    "identity.occupation": {"card": "single"},
    "identity.city": {"card": "single"},
    "identity.mbti": {"card": "single",
                      "enum": ["ENFP", "ENTP", "ESFP", "ESTP", "ENFJ", "ENTJ", "ESFJ", "ESTJ",
                               "INFP", "INTP", "ISFP", "ISTP", "INFJ", "INTJ", "ISFJ", "ISTJ"]},
    "identity.zodiac": {"card": "single", "enum": ["白羊座", "金牛座", "双子座", "巨蟹座", "狮子座",
                                                    "处女座", "天秤座", "天蝎座", "射手座", "摩羯座",
                                                    "水瓶座", "双鱼座"]},
    "identity.self_reference": {"card": "single"},
    "identity.summary": {"card": "single"},
    "identity.relationship.kind": {"card": "single",
                                   "enum": ["ex_partner", "ambiguous", "friend", "family", "mentor", "other"]},
    "identity.relationship.status": {"card": "single",
                                     "enum": ["separated", "together", "ambiguous", "ended_with_death", "other"]},
    "identity.relationship.together_duration_text": {"card": "single"},
    "identity.relationship.apart_duration_text": {"card": "single"},
    "identity.relationship.how_met": {"card": "single"},
    "identity.relationship.breakup_reason": {"card": "single"},
    "identity.relationship.current_contact_state": {"card": "single"},
    "identity.relationship.pretend_together": {"card": "single", "bool": True},
    # L2 speech
    "speech_style.catchphrases": {"card": "array"},
    "speech_style.tone_particles": {"card": "array"},
    "speech_style.tone": {"card": "array"},
    "speech_style.message_length": {"card": "single",
                                    "enum": ["short_burst", "mixed", "long_form"]},
    "speech_style.punctuation": {"card": "single"},
    "speech_style.emoji_usage": {"card": "single"},
    "speech_style.typos_abbreviations": {"card": "array"},
    "speech_style.forms_of_address_user": {"card": "array"},
    # L3 emotional
    "emotional_pattern.attachment_style": {"card": "single",
                                           "enum": ["secure", "anxious", "avoidant", "disorganized"]},
    "emotional_pattern.love_languages": {"card": "array", "enum": ["words_of_affirmation", "quality_time",
                                                                    "receiving_gifts", "acts_of_service",
                                                                    "physical_touch"]},
    "emotional_pattern.emotion_expressions.expression_of_affection": {"card": "single", "low_risk": True},
    "emotional_pattern.emotion_expressions.when_angry": {"card": "single", "low_risk": True},
    "emotional_pattern.emotion_expressions.when_sad": {"card": "single", "low_risk": True},
    "emotional_pattern.emotion_expressions.when_happy": {"card": "single", "low_risk": True},
    "emotional_pattern.emotion_expressions.when_jealous": {"card": "single", "low_risk": True},
    "emotional_pattern.emotion_expressions.how_comforts": {"card": "single", "low_risk": True},
    "emotional_pattern.triggers.anger_triggers": {"card": "array"},
    "emotional_pattern.triggers.sensitive_topics": {"card": "array"},
    "emotional_pattern.triggers.joy_triggers": {"card": "array"},
    # L4 relationship
    "relationship_behavior.role": {"card": "single", "low_risk": True},
    "relationship_behavior.conflict_pattern": {"card": "single", "low_risk": True},
    "relationship_behavior.make_up_pattern": {"card": "single", "low_risk": True},
    "relationship_behavior.contact_frequency": {"card": "single"},
    "relationship_behavior.active_hours": {"card": "single"},
    "relationship_behavior.boundaries": {"card": "array"},
}

# L0/L1 身份例外：允许 direct_quote / user_report_only / correction（不含 inferred）
L0L1_EXCEPT = {
    "layer0_rules.do_not_say", "layer0_rules.specific_edges", "layer0_rules.reality_boundary",
    "identity.name_or_alias", "identity.age", "identity.gender", "identity.occupation",
    "identity.city", "identity.self_reference",
    "identity.relationship.kind", "identity.relationship.status",
    "identity.relationship.together_duration_text", "identity.relationship.apart_duration_text",
    "identity.relationship.how_met", "identity.relationship.breakup_reason",
    "identity.relationship.current_contact_state", "identity.relationship.pretend_together",
}

# 可读枚举 → schema 枚举 的少量别名（不含则需精确匹配）
ENUM_ALIAS = {"安全型": "secure", "焦虑型": "anxious", "回避型": "avoidant", "混乱型": "disorganized"}


def _coerce_value(fd: dict, text) -> Optional:
    if fd.get("int"):
        if isinstance(text, int) and not isinstance(text, bool):
            return text
        if isinstance(text, str) and text.strip().isdigit():
            return int(text.strip())
        return None
    if fd.get("bool"):
        if isinstance(text, bool):
            return text
        if isinstance(text, str):
            return {"true": True, "false": False, "yes": True, "no": False}.get(text.strip().lower())
        return None
    enum = fd.get("enum")
    if enum:
        if isinstance(text, str):
            t = text.strip()
            if t in enum:
                return t
            if t in ENUM_ALIAS:
                return ENUM_ALIAS[t]
            return None
        return None
    if isinstance(text, str):
        return text
    if isinstance(text, (int, float)):
        return str(text)
    return None


# ---------------------------------------------------------------------------
# 空 v1.2 骨架
# ---------------------------------------------------------------------------
def empty_pm(name_or_alias: str) -> dict:
    return {
        "schema_version": "1.2", "revision": 1,
        "created_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "updated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "persona": {
            "layer0_rules": {"do_not_say": [], "specific_edges": [], "reality_boundary": None},
            "identity": {"name_or_alias": None, "relationship": {}},
            "speech_style": {"catchphrases": [], "examples": []},
            "emotional_pattern": {},
            "relationship_behavior": {},
        },
        "memory": {b: [] for b in MEMORY_BUCKETS},
        "corrections": [],
    }


def claim_id(field: str, value) -> str:
    return "pc_" + _sha1(f"{field}\x1f{_canonical(str(value))}")[:16]


# ---------------------------------------------------------------------------
# persona claim 写读
# ---------------------------------------------------------------------------
def _walk_get(obj: dict, path: str):
    parts = path.split(".")
    cur = obj
    for p in parts:
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            return None
    return cur


def _walk_ensure(obj: dict, path: str):
    parts = path.split(".")
    cur = obj
    for p in parts[:-1]:
        if p not in cur or cur[p] is None:
            cur[p] = {}
        cur = cur[p]
    return cur


def write_claim(pm: dict, field: str, value, basis: str, evidence_ids, confidence: float) -> bool:
    fd = FIELDS.get(field)
    if fd is None:
        return False
    val = _coerce_value(fd, value)
    if val is None:
        return False
    holder = _walk_ensure(pm["persona"], field)
    leaf = field.split(".")[-1]
    claim = {"claim_id": claim_id(field, val), "value": val,
             "evidence_ids": sorted(set(evidence_ids)),
             "confidence": round(max(0.0, min(1.0, confidence)), 3), "basis": basis}
    if fd["card"] == "array":
        arr = holder.get(leaf)
        if arr is None:
            arr = []
            holder[leaf] = arr
        for c in arr:
            if c.get("value") == val:
                c["evidence_ids"] = sorted(set(c["evidence_ids"]) | set(evidence_ids))
                c["confidence"] = max(c["confidence"], claim["confidence"])
                return True
        arr.append(claim)
        return True
    # single：reality_boundary 等允许 null 覆盖；若已存在同值 reinforce，否则覆盖
    existing = holder.get(leaf)
    if isinstance(existing, dict) and existing.get("value") == val:
        existing["evidence_ids"] = sorted(set(existing.get("evidence_ids", [])) | set(evidence_ids))
        existing["confidence"] = max(existing.get("confidence", 0), claim["confidence"])
        return True
    holder[leaf] = claim
    return True


def read_claim_value(pm: dict, field: str):
    return _walk_get(pm["persona"], field)


# ---------------------------------------------------------------------------
# 空 L0 / single 字段需要 null 合法：identity.name_or_alias 是必填且非 null
# 骨架里 name_or_alias=None 会 schema 失败 —— 但它是 required，需先放用户值。
# 我们通过 write_claim("identity.name_or_alias", name, "user_report_only", []) 由调用方在骨架后写入。
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# interpreter
# ---------------------------------------------------------------------------
def _heuristic_bucket(value: str) -> str:
    # inside jokes 优先（只有两人懂的梗即使含吵架词也属梗）
    for kw in ("只有我俩", "只有我们懂", "暗号", "我们的梗", "说『", "绿豆", "团子"):
        if kw in value:
            return "inside_jokes"
    for kw in ("分手",):
        if kw in value:
            return "breakup"
    for kw in ("吵架", "争吵", "冷战", "闹翻"):
        if kw in value:
            return "conflicts"
    for kw in ("喜欢", "爱喝", "不爱", "讨厌", "偏好", "爱吃", "不吃", "喜欢喝"):
        if kw in value:
            return "preferences"
    for kw in ("开心", "甜蜜", "心动", "第一次约会"):
        if kw in value:
            return "happy_memories"
    for kw in ("认识", "在一起", "谈过"):
        if kw in value:
            return "core_facts"
    return "shared_experiences"


def interpret(group: dict, cand_by_id: dict, llm: Optional[Callable]) -> dict:
    """返回 {"bucket": str|null, "persona": [ {leaf, value_text} ], "memory_text": str|null}"""
    rep_id = group["representative"]["candidate_id"]
    rep = cand_by_id.get(rep_id, {})
    value = rep.get("claim", {}).get("value", "")
    if llm is None:
        return {"bucket": _heuristic_bucket(value), "persona": [], "memory_text": None}
    prompt = (
        "你是 Persona/Memory Builder 的解释器。给定一个证据组代表候选，决定它应进入哪个 memory 桶"
        f"（{'|'.join(MEMORY_BUCKETS)}）或 null，以及是否应写成 persona 叶子（可选叶子列表见下）。\n"
        "叶子白名单（只能选其一）：identity.occupation|identity.city|identity.mbti|identity.zodiac|"
        "identity.self_reference|identity.summary|identity.relationship.kind|identity.relationship.status|"
        "identity.relationship.together_duration_text|identity.relationship.apart_duration_text|"
        "identity.relationship.how_met|identity.relationship.breakup_reason|"
        "identity.relationship.current_contact_state|speech_style.catchphrases|speech_style.tone_particles|"
        "speech_style.tone|speech_style.message_length|speech_style.punctuation|speech_style.emoji_usage|"
        "speech_style.typos_abbreviations|speech_style.forms_of_address_user|"
        "emotional_pattern.attachment_style|emotional_pattern.love_languages|"
        "emotional_pattern.triggers.anger_triggers|emotional_pattern.triggers.sensitive_topics|"
        "emotional_pattern.triggers.joy_triggers|relationship_behavior.role|"
        "relationship_behavior.conflict_pattern|relationship_behavior.make_up_pattern|"
        "relationship_behavior.contact_frequency|relationship_behavior.active_hours|"
        "relationship_behavior.boundaries|layer0_rules.do_not_say|layer0_rules.specific_edges|"
        "layer0_rules.reality_boundary\n"
        "只输出 JSON: {\"bucket\": 桶或null, \"persona\": [{\"leaf\": 叶子, \"value_text\": 值}]}\n"
        "证据: " + json.dumps({"value": value, "basis": rep.get("claim", {}).get("basis"),
                               "evidence_type": rep.get("evidence_type"),
                               "speaker": rep.get("speaker_role")}, ensure_ascii=False)
    )
    try:
        raw = llm(prompt)
    except Exception:
        return {"bucket": _heuristic_bucket(value), "persona": [], "memory_text": None}
    m = re.search(r"\{[\s\S]*\}", raw or "")
    if not m:
        return {"bucket": _heuristic_bucket(value), "persona": [], "memory_text": None}
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"bucket": _heuristic_bucket(value), "persona": [], "memory_text": None}
    bucket = obj.get("bucket")
    if bucket not in MEMORY_BUCKETS:
        bucket = None
    persona = []
    for p in (obj.get("persona") or []):
        leaf = p.get("leaf")
        txt = p.get("value_text")
        if leaf in FIELDS and isinstance(txt, str) and txt.strip():
            persona.append({"leaf": leaf, "value_text": txt.strip()})
    return {"bucket": bucket, "persona": persona, "memory_text": None}


# ---------------------------------------------------------------------------
# memory
# ---------------------------------------------------------------------------
def memory_item_id(bucket: str, content: str) -> str:
    return "mi_" + _sha1(f"{bucket}\x1f{_canonical(content)}")[:16]


def make_memory(bucket: str, content: str, cand_ids: List[str], cand_by_id: dict,
                status="active", supersede_kind=None, superseded_by=None,
                history=None, valid_period=None) -> dict:
    src_refs = sorted({s for cid in cand_ids for s in (cand_by_id.get(cid, {}).get("source_refs") or [])})
    conf = max([(cand_by_id.get(cid, {}).get("confidence") or 0.0) for cid in cand_ids] or [0.0])
    rep = cand_by_id.get(cand_ids[0], {}) if cand_ids else {}
    return {
        "id": memory_item_id(bucket, content),
        "content": content,
        "importance": 3,
        "confidence": round(conf, 3),
        "source_type": rep.get("source_type") or "unknown",
        "source_ref": src_refs[0] if src_refs else None,
        "status": status,
        "supersede_kind": supersede_kind,
        "superseded_by": superseded_by,
        "corrected": False,
        "evidence_ids": sorted(set(cand_ids)),
        "conflicts_with": [],
        "history": history,
        "valid_period": valid_period,
        "created_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "updated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "tags": [],
    }


# ---------------------------------------------------------------------------
# 主构建
# ---------------------------------------------------------------------------
def build_persona_memory(*, bundle: dict, candidate_set: dict, name_or_alias: str,
                         corrections: Optional[List[dict]] = None,
                         llm: Optional[Callable] = None) -> dict:
    warnings: List[str] = []
    b_errs = _schema_errs(_bundle_validator, bundle)
    if b_errs:
        return {"ok": False, "persona_memory": None,
                "errors": ["bundle schema 失败: " + b_errs[0]], "warnings": []}
    cand_by_id = {c["candidate_id"]: c for c in candidate_set.get("candidates", [])}

    pm = empty_pm(name_or_alias)
    # 先写 name_or_alias（用户提供，required & 非 null）
    write_claim(pm, "identity.name_or_alias", name_or_alias, "user_report_only", [], 1.0)

    # 索引 groups
    groups_by_id = {g["merge_group_id"]: g for g in bundle["groups"]}

    # 所有 memory 先入 pending：{(bucket, mi_id): item}，冲突关联后再落 pm
    pending: Dict[str, tuple] = {}   # key = f"{bucket}\x1f{mi_id}"

    def upsert(bucket: str, item: dict):
        key = f"{bucket}\x1f{item['id']}"
        existing = pending.get(key)
        if existing is not None:
            old = existing[1]
            old["evidence_ids"] = sorted(set(old["evidence_ids"]) | set(item["evidence_ids"]))
            old["confidence"] = max(old["confidence"], item["confidence"])
            return item["id"]
        pending[key] = (bucket, item)
        return item["id"]

    # evolution 容器：处理 temporal 组间关系（history 保留，不删旧）
    temporal_edges = [r for r in bundle.get("group_level_relations", [])
                      if r["relation_type"] == "temporal_evolution"]
    consumed = set()

    def tb(t):
        if not t:
            return None
        try:
            datetime.fromisoformat(str(t).replace("Z", "+00:00"))
        except ValueError:
            return None
        return {"value": str(t)[:10], "precision": "exact"}

    for te in temporal_edges:
        ga, gb = te["group_a"], te["group_b"]
        gA, gB = groups_by_id.get(ga), groups_by_id.get(gb)
        if not gA or not gB:
            continue
        earlier, later = (gA, gB) if te.get("direction") in (None, "a_earlier_b_later") else (gB, gA)
        consumed.add(earlier["merge_group_id"])
        consumed.add(later["merge_group_id"])
        e_rep = cand_by_id.get(earlier["representative"]["candidate_id"], {})
        l_rep = cand_by_id.get(later["representative"]["candidate_id"], {})
        e_val = e_rep.get("claim", {}).get("value", "")
        l_val = l_rep.get("claim", {}).get("value", "")
        e_time, l_time = e_rep.get("observed_at"), l_rep.get("observed_at")
        e_ids = [m["candidate_id"] for m in earlier["members"]]
        l_ids = [m["candidate_id"] for m in later["members"]]
        hb = _heuristic_bucket(l_val)
        bucket = hb if hb != "shared_experiences" else "preferences"
        container = make_memory(
            bucket, content=f"{e_val}；后来：{l_val}",
            cand_ids=l_ids, cand_by_id=cand_by_id, status="active",
            history=[
                {"value": e_val, "valid_from": tb(e_time), "valid_to": tb(l_time), "evidence_ids": sorted(e_ids)},
                {"value": l_val, "valid_from": tb(l_time), "valid_to": None, "evidence_ids": sorted(l_ids)},
            ],
            valid_period={"from": tb(l_time), "to": None})
        upsert(bucket, container)

    # 冲突边索引（仅标记，不删）
    conflict_edges = [r for r in bundle.get("group_level_relations", [])
                      if r["relation_type"] == "conflict"]
    groups_in_conflict = {gid for ce in conflict_edges for gid in (ce["group_a"], ce["group_b"])}

    for g in sorted(groups_by_id.values(), key=lambda x: x["merge_group_id"]):
        gid = g["merge_group_id"]
        if gid in consumed:
            continue
        rep_id = g["representative"]["candidate_id"]
        rep = cand_by_id.get(rep_id, {})
        if not rep:
            continue
        members = [m["candidate_id"] for m in g["members"]]
        sp = rep.get("speaker_role")
        et = rep.get("evidence_type")
        basis = rep.get("claim", {}).get("basis")
        value = rep.get("claim", {}).get("value", "")

        # eligibility：纯 user_correction 组不作为独立 memory（纠正是 overlay，非新事实）
        if et == "user_correction":
            continue

        interp = interpret(g, cand_by_id, llm)
        bucket = interp["bucket"] or _heuristic_bucket(value)

        # ---- persona 途径（决定性门槛 Q3；L0/L1 例外；inferred 不进 Q5；speaker 程序权威）----
        for p in interp["persona"]:
            leaf = p["leaf"]
            fd = FIELDS[leaf]
            # speaker 程序权威：只有 target 可产生 decisive direct；user→user_report_only；
            # other/unknown 一律不得进 persona（含 L0/L1）
            if sp not in ("target", "user"):
                warnings.append(f"group {gid} → persona {leaf} speaker={sp} 禁入，跳过")
                continue
            use_basis = basis
            if sp == "user":
                use_basis = "user_report_only"   # user_narration 永不 target direct
            if use_basis == "inferred" and not fd.get("low_risk"):
                warnings.append(f"group {gid} → persona {leaf} inferred 禁入，跳过")
                continue
            # L0 只允许 direct_quote / user_report_only / correction（inferred 已在上面拦；multi/single_weak 拦）
            if fd.get("l0") and use_basis in ("multi_evidence", "single_weak", "inferred"):
                warnings.append(f"group {gid} → L0 {leaf} basis={use_basis} 禁入，跳过")
                continue
            # Q3 决定性门槛：direct / multi 决定性；user_report/correction 仅在 L0/L1 身份锚可用
            if use_basis in ("user_report_only", "correction") and leaf not in L0L1_EXCEPT:
                warnings.append(f"group {gid} → persona {leaf} basis={use_basis} 不足决定性，跳过")
                continue
            if use_basis in ("single_weak",) and leaf not in L0L1_EXCEPT:
                warnings.append(f"group {gid} → persona {leaf} basis=single_weak 不足决定性，跳过")
                continue
            # L0 do_not_say/specific_edges/reality_boundary：user_report_only 仅当来自 user_correction
            # （absence-of-evidence / 用户单方回忆不得凭空生成"ta绝不说X"）
            if fd.get("l0") and use_basis == "user_report_only" and et != "user_correction":
                warnings.append(f"group {gid} → L0 {leaf} user_report(非correction) 禁入，跳过")
                continue
            # 解释性高层 trait（L3 依恋/爱的语言/情绪、L4 role 等）单条证据不足以决定性：
            # 需 ≥2 独立候选 或 叶子为低风险解释字段(low_risk 允许 inferred 即解释)
            if leaf in ("emotional_pattern.attachment_style", "emotional_pattern.love_languages") \
                    and len(members) < 2:
                warnings.append(f"group {gid} → persona {leaf} 单条证据不足以支撑解释性 trait，跳过")
                continue
            conf = max([(cand_by_id.get(c, {}).get("confidence") or 0.0) for c in members] or [0.0])
            write_claim(pm, leaf, p["value_text"], use_basis, members, conf)

        # ---- memory 途径 ----
        status = "pending_confirmation" if gid in groups_in_conflict else "active"
        item = make_memory(bucket, value, members, cand_by_id, status=status)
        upsert(bucket, item)

    # 冲突关联：group-level conflict → 双方 memory pending + conflicts_with
    for ce in conflict_edges:
        ga, gb = ce["group_a"], ce["group_b"]
        items_a = [it for (b_, it) in pending.values()
                   if set(it["evidence_ids"]) & set(_g_cids(groups_by_id.get(ga)))]
        items_b = [it for (b_, it) in pending.values()
                   if set(it["evidence_ids"]) & set(_g_cids(groups_by_id.get(gb)))]
        for a in items_a:
            for b in items_b:
                if a["id"] != b["id"]:
                    for x, y in ((a, b), (b, a)):
                        if y["id"] not in x["conflicts_with"]:
                            x["conflicts_with"].append(y["id"])

    # 落 pm.memory
    for (bucket, item) in pending.values():
        arr = pm["memory"].setdefault(bucket, [])
        # merge by id（同桶同 id → 合并）
        found = None
        for i, it in enumerate(arr):
            if it["id"] == item["id"]:
                found = i
                break
        if found is not None:
            old = arr[found]
            old["evidence_ids"] = sorted(set(old["evidence_ids"]) | set(item["evidence_ids"]))
            old["confidence"] = max(old["confidence"], item["confidence"])
        else:
            arr.append(item)

    # correction overlay
    apply_corrections(pm, corrections or [], cand_by_id, warnings)

    # provenance assertion
    if not _provenance_ok(pm, cand_by_id):
        return {"ok": False, "persona_memory": None,
                "errors": ["evidence_ids 无法回溯到 CandidateSet"], "warnings": warnings}

    verrs = _schema_errs(_pm_validator, pm)
    if verrs:
        return {"ok": False, "persona_memory": None,
                "errors": ["persona_memory v1.2 schema 失败: " + verrs[0]
                           + (f" (+{len(verrs)-1})" if len(verrs) > 1 else "")],
                "warnings": warnings}
    pm["updated_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    return {"ok": True, "persona_memory": pm, "errors": [], "warnings": warnings}


def _g_cids(g):
    return [m["candidate_id"] for m in g["members"]] if g else []


def _bucket_of(item: dict, pm: dict) -> str:
    """找到该 item 所在桶（add 时即定位；此处用于把 memory_by_id 落桶）。"""
    for b in MEMORY_BUCKETS:
        for it in pm["memory"][b]:
            if it["id"] == item["id"]:
                return b
    # 不在任何桶 → 按启发补
    return _heuristic_bucket(item["content"])


def _store_memory(pm: dict, bucket: str, item: dict):
    arr = pm["memory"].setdefault(bucket, [])
    for i, it in enumerate(arr):
        if it["id"] == item["id"]:
            arr[i] = item   # replace/merge
            return
    arr.append(item)


def _locate_persona_claim(pm_persona: dict, cid: str):
    """定位 persona claim：返回 (field_path, holder_dict|None, array|None, index|None, claim)。

    single leaf: claim 存在 holder[leaf]，返回 (field, holder, leaf_key)
    array leaf:   claim 在 holder[leaf][i]，返回 (field, holder, leaf_key)
    统一返回 (field_path, holder, leaf_key, is_array)
    """
    # 遍历 FIELDS 叶子
    for field, fd in FIELDS.items():
        holder = _walk_get(pm_persona, field.rsplit(".", 1)[0] if "." in field else "")
        leaf = field.split(".")[-1]
        # 用 walk 取容器
        cur = pm_persona
        parts = field.split(".")
        ok = True
        for p in parts[:-1]:
            if isinstance(cur, dict) and p in cur and cur[p] is not None:
                cur = cur[p]
            else:
                ok = False
                break
        if not ok:
            continue
        if fd["card"] == "array":
            arr = cur.get(parts[-1])
            if isinstance(arr, list):
                for i, c in enumerate(arr):
                    if isinstance(c, dict) and c.get("claim_id") == cid:
                        return (field, cur, parts[-1], i, c)
        else:
            c = cur.get(parts[-1])
            if isinstance(c, dict) and c.get("claim_id") == cid:
                return (field, cur, parts[-1], None, c)
    return None


def apply_persona_correction(pm: dict, corr: dict, warnings: List[str]) -> bool:
    """persona_claim correction：产生 corrected value 对应的新 claim（新确定性 claim_id），
    保留旧 claim/旧 id 的审计（single leaf 由顶层 corrections 承载旧值），
    corrected_value 的 evidence_ids 为空（其 provenance 是 correction，不是旧候选）。
    返回是否命中目标。"""
    tid = corr.get("target_id")
    cv = corr.get("corrected_value")
    loc = _locate_persona_claim(pm["persona"], tid)
    if loc is None:
        return False
    field, holder, leaf_key, _idx, old_claim = loc
    fd = FIELDS[field]
    val = _coerce_value(fd, cv)   # 类型/枚举约束；int/bool/enum 依目标字段
    if cv is not None and val is None:
        warnings.append(f"correction {corr.get('id')} corrected_value 不符合 {field} 类型/枚举，拒绝应用")
        return True  # 命中但值非法 → 记录 warning 不应用
    if fd["card"] == "array":
        arr = holder[leaf_key]
        if val is None:
            # suppression（值 null）：数组无法"置空"，保留并 warning
            warnings.append(f"correction {corr.get('id')} 数组叶子 {field} 不支持 suppress，保留原 claim")
            return True
        new_cid = claim_id(field, val)
        # 若 corrected value 的 claim 已存在 → 不重复
        for c in arr:
            if c.get("claim_id") == new_cid:
                return True
        arr.append({"claim_id": new_cid, "value": val, "evidence_ids": [],
                    "confidence": 1.0, "basis": "correction"})
        return True
    # single leaf：v1.2 只允许一个 claim → 用 corrected value 的 claim 替换活值，
    # 旧 value/claim_id 由顶层 corrections 记录（original_value/target_id）承载审计（v1.2 无 claim status）。
    if val is None:
        # suppression：single leaf 置 null
        holder[leaf_key] = None
        return True
    new_cid = claim_id(field, val)
    holder[leaf_key] = {"claim_id": new_cid, "value": val, "evidence_ids": [],
                        "confidence": 1.0, "basis": "correction"}
    return True


def apply_corrections(pm: dict, corrections: List[dict], cand_by_id: dict, warnings: List[str]):
    for corr in corrections:
        if corr.get("status") != "active":
            continue
        tk = corr.get("target_kind")
        tid = corr.get("target_id")
        cv = corr.get("corrected_value")
        orig_value = None
        if tk == "persona_claim":
            loc = _locate_persona_claim(pm["persona"], tid)
            if loc is None:
                warnings.append(f"correction {corr.get('id')} 未命中 persona claim {tid}（跨 run 漂移或证据未复现）")
            else:
                orig_value = loc[4].get("value")
                apply_persona_correction(pm, corr, warnings)
        elif tk == "memory_item":
            for b in MEMORY_BUCKETS:
                for it in pm["memory"][b]:
                    if it["id"] == tid and it["status"] in ("active", "pending_confirmation"):
                        it["status"] = "superseded"
                        it["supersede_kind"] = "corrected"
                        it["superseded_by"] = corr.get("id")
                        it["corrected"] = True
                        orig_value = it.get("content")
        # 顶层 corrections 统一留痕（含 original_value，供审计/回滚）
        pm["corrections"].append({
            "id": corr.get("id"), "target_kind": tk, "target_id": tid,
            "target_path": corr.get("target_path"), "original_value": orig_value,
            "corrected_value": cv, "basis_override": "correction",
            "user_statement": corr.get("user_statement"), "status": "active",
            "superseded_by": None,
            "created_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        })


def _provenance_ok(pm: dict, cand_by_id: dict) -> bool:
    ok = True

    def chk(o):
        nonlocal ok
        if isinstance(o, dict):
            if isinstance(o.get("claim_id"), str) and "evidence_ids" in o:
                for eid in o["evidence_ids"]:
                    if eid not in cand_by_id:
                        ok = False
            for v in o.values():
                chk(v)
        elif isinstance(o, list):
            for v in o:
                chk(v)
    chk(pm["persona"])
    for b in MEMORY_BUCKETS:
        for it in pm["memory"][b]:
            for eid in it.get("evidence_ids", []):
                if eid not in cand_by_id:
                    ok = False
    return ok


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Persona/Memory Builder（诊断）")
    ap.add_argument("--bundle", required=True)
    ap.add_argument("--candidate-set", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--corrections", default=None)
    ap.add_argument("--output", default=None)
    args = ap.parse_args(argv)
    b = json.load(open(args.bundle, encoding="utf-8"))
    cs = json.load(open(args.candidate_set, encoding="utf-8"))
    corr = json.load(open(args.corrections, encoding="utf-8")) if args.corrections else None
    r = build_persona_memory(bundle=b, candidate_set=cs, name_or_alias=args.name, corrections=corr)
    if not r["ok"]:
        print("ERROR:", r["errors"])
        return 2
    for w in r["warnings"]:
        print("WARN:", w)
    if args.output:
        json.dump(r["persona_memory"], open(args.output, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
    else:
        print(json.dumps(r["persona_memory"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
