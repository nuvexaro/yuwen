#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 Stage 5.6 golden cases（case_001..case_014）。

只生成目录与 JSON；messages.json 是合法 ChatImport v1.2（含 confirmed target）。
生成后由 eval_runner 走真实冻结链路评测。
"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))


def chat_import(messages, src="eval", title="小明", target_confirmed=True,
                extra_participants=None):
    participants = [
        {"role": "user", "account_id": None, "names": ["我"], "match_method": "name_exact",
         "confidence": 0.85, "confirmed": True},
        {"role": "target", "account_id": None, "names": ["小明"], "match_method": "name_exact",
         "confidence": 0.9, "confirmed": target_confirmed},
    ]
    if extra_participants:
        participants += extra_participants
    return {"schema_version": "1.2", "platform": "wechat", "source_format": "txt",
            "source_ref": src, "conversation_title": title, "default_sender_role": "unknown",
            "participants": participants, "messages": messages}


def msg(mid, body, sender_role="target", sent="2024-01-15T20:00:00", name="小明"):
    return {"id": mid, "content_fingerprint": "f_" + mid, "sequence": 0,
            "sent_at": sent, "sent_at_raw": sent.replace("T", " ") if sent else None,
            "sender": {"role": sender_role, "name": name, "sender_key": name},
            "content_type": None, "body": body, "media": None,
            "reply_to_message_id": None, "is_recalled": None, "in_group_chat": None}


def write_case(cid, meta, messages, expected_p=None, expected_m=None, expected_neg=None, anns=None):
    d = os.path.join(HERE, cid)
    os.makedirs(d, exist_ok=True)
    meta.setdefault("case_id", cid)
    json.dump({"schema_version": "1.2", **chat_import(messages)}, open(os.path.join(d, "messages.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    json.dump(meta, open(os.path.join(d, "meta.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    for fname, obj in (("expected_persona.json", expected_p), ("expected_memory.json", expected_m),
                       ("expected_negative.json", expected_neg), ("annotations.json", anns)):
        if obj is not None:
            json.dump(obj, open(os.path.join(d, fname), "w", encoding="utf-8"), ensure_ascii=False, indent=2)


NEG_COMMON = ["高冷", "温柔", "回避型依恋", "恋爱脑", "控制欲", "焦虑型依恋", "共情能力强", "缺乏安全感"]

# case_001 正常 memory（偏好）
write_case("case_001",
    {"name_or_alias": "小明", "tags": ["normal", "memory", "preference"], "difficulty": "easy",
     "evaluation_dimensions": ["memory_accuracy", "evidence_fidelity", "provenance"]},
    [msg("m_1", "我不喜欢别人突然给我打电话"), msg("m_2", "我最爱喝奶茶"), msg("m_3", "我半夜喜欢听民谣")],
    expected_p={"traits": []},
    expected_m={"preferences": ["不喜欢别人突然打电话", "爱喝奶茶", "听民谣"]},
    expected_neg={"traits": NEG_COMMON},
    anns=[
        {"target": {"kind": "memory_item", "memoryItem_id": "mi?", "bucket": "preferences",
                    "value": "我不喜欢别人突然给我打电话"}, "evidence_support": "SUPPORTED",
         "target_placement": "memory", "overreach": False, "inference_quality": "direct",
         "confidence_rating": "reasonable", "provenance_complete": True},
    ])

# case_002 正常 persona（依赖证据 → 但 builder 无 LLM 保守，故 expected persona 为空体现"保守回退"）
write_case("case_002",
    {"name_or_alias": "小明", "tags": ["persona", "conservative"], "difficulty": "medium",
     "evaluation_dimensions": ["persona_precision", "negative"]},
    [msg("m_1", "我从来不喜欢社交"), msg("m_2", "周末我只想一个人待着")],
    expected_p={"traits": []},  # 保守路径不臆造 persona trait
    expected_m={"preferences": ["不喜欢社交", "一个人待着"]},
    expected_neg={"traits": NEG_COMMON + ["社恐", "孤僻"]},
    anns=[
        {"target": {"kind": "persona_claim", "claim_id": None, "value": "喜欢独处"},
         "evidence_support": "PARTIALLY_SUPPORTED", "target_placement": "memory",
         "overreach": False, "inference_quality": "reasonable_inference",
         "confidence_rating": "reasonable", "provenance_complete": False},
    ])

# case_003 极少证据 → 无 overreach
write_case("case_003",
    {"name_or_alias": "小明", "tags": ["sparse", "overreach", "negative"], "difficulty": "easy",
     "evaluation_dimensions": ["overreach", "hallucination"]},
    [msg("m_1", "嗯"), msg("m_2", "哈哈"), msg("m_3", "晚安"), msg("m_4", "你吃饭了吗")],
    expected_p={"traits": []},
    expected_m={"shared_experiences": []},
    expected_neg={"traits": NEG_COMMON + ["高冷", "温柔"]},
    anns=[])

# case_004 conflict 喜欢猫 vs 讨厌猫
write_case("case_004",
    {"name_or_alias": "小明", "tags": ["conflict"], "difficulty": "medium",
     "evaluation_dimensions": ["conflict_safety"]},
    [msg("m_1", "我喜欢猫"), msg("m_2", "我特别讨厌猫")],
    expected_p={"traits": []},
    expected_m={"preferences": ["喜欢猫", "讨厌猫"]},
    expected_neg={"traits": []},
    anns=[
        {"target": {"kind": "memory_item", "memoryItem_id": None, "bucket": "preferences", "value": "喜欢猫"},
         "evidence_support": "SUPPORTED", "target_placement": "memory", "overreach": False,
         "inference_quality": "direct", "confidence_rating": "reasonable", "provenance_complete": True},
        {"target": {"kind": "memory_item", "memoryItem_id": None, "bucket": "preferences", "value": "讨厌猫"},
         "evidence_support": "SUPPORTED", "target_placement": "memory", "overreach": False,
         "inference_quality": "direct", "confidence_rating": "reasonable", "provenance_complete": True},
    ])

# case_005 temporal evolution 2022 vs 2025
write_case("case_005",
    {"name_or_alias": "小明", "tags": ["temporal"], "difficulty": "hard",
     "evaluation_dimensions": ["temporal_accuracy", "temporal_non_destructive"]},
    [msg("m_1", "2022年我喜欢喝奶茶", sent="2022-06-01T12:00:00"),
     msg("m_2", "2025年我已经不喝奶茶了", sent="2025-01-01T12:00:00")],
    expected_p={"traits": []},
    expected_m={"preferences": []},  # 容器单条含 history
    expected_neg={"traits": []},
    anns=[
        {"target": {"kind": "memory_item", "memoryItem_id": None, "bucket": "preferences", "value": "曾爱喝奶茶后戒"},
         "evidence_support": "SUPPORTED", "target_placement": "memory", "overreach": False,
         "inference_quality": "direct", "confidence_rating": "reasonable", "provenance_complete": True},
    ])

# case_006 unknown/fuzzy time → 不建立错误 temporal
write_case("case_006",
    {"name_or_alias": "小明", "tags": ["fuzzy-time"], "difficulty": "hard",
     "evaluation_dimensions": ["temporal_accuracy"]},
    [msg("m_1", "我喜欢喝奶茶", sent=None), msg("m_2", "我已经不喝奶茶了", sent=None)],
    expected_p={"traits": []},
    expected_m={},
    expected_neg={"traits": []},
    anns=[])

# case_007 user_narration vs target_message
write_case("case_007",
    {"name_or_alias": "小明", "tags": ["user-narration", "provenance"], "difficulty": "medium",
     "evaluation_dimensions": ["user_narration", "evidence_fidelity"]},
    [msg("m_1", "我自己不太爱说话"), msg("m_2", "用户回忆：她好像很内向", sender_role="user", name="我")],
    expected_p={"traits": []},
    expected_m={},
    expected_neg={"traits": []},
    anns=[
        {"target": {"kind": "memory_item", "memoryItem_id": None, "bucket": "preferences", "value": "不太爱说话"},
         "evidence_support": "SUPPORTED", "target_placement": "memory", "overreach": False,
         "inference_quality": "direct", "confidence_rating": "reasonable", "provenance_complete": True},
    ])

# case_008 supporting_related 噪声（喜欢猫 + 养过猫）
write_case("case_008",
    {"name_or_alias": "小明", "tags": ["related-noise"], "difficulty": "medium",
     "evaluation_dimensions": ["supporting_related", "persona_precision"]},
    [msg("m_1", "我喜欢猫"), msg("m_2", "我养过一只猫")],
    expected_p={"traits": []},
    expected_m={"preferences": ["喜欢猫"], "shared_experiences": ["养过一只猫"]},
    expected_neg={"traits": ["爱猫成痴"]},
    anns=[])

# case_009 duplicate evidence（同句两条）→ dedup
write_case("case_009",
    {"name_or_alias": "小明", "tags": ["duplicate", "dedup"], "difficulty": "easy",
     "evaluation_dimensions": ["memory_dedup"]},
    [msg("m_1", "我特别讨厌下雨"), msg("m_2", "我特别讨厌下雨")],
    expected_p={"traits": []},
    expected_m={"preferences": ["讨厌下雨"]},
    expected_neg={"traits": []},
    anns=[
        {"target": {"kind": "memory_item", "memoryItem_id": None, "bucket": "preferences", "value": "讨厌下雨"},
         "evidence_support": "SUPPORTED", "target_placement": "memory", "overreach": False,
         "inference_quality": "direct", "confidence_rating": "reasonable", "provenance_complete": True},
    ])

# case_010 单条 weak evidence → 不产 persona
write_case("case_010",
    {"name_or_alias": "小明", "tags": ["weak"], "difficulty": "easy",
     "evaluation_dimensions": ["persona_precision", "sparse"]},
    [msg("m_1", "今天有点累")],
    expected_p={"traits": []},
    expected_m={},
    expected_neg={"traits": NEG_COMMON + ["工作狂", "消极"]},
    anns=[])

# case_011 多条相关但推不出人格
write_case("case_011",
    {"name_or_alias": "小明", "tags": ["related-no-trait"], "difficulty": "medium",
     "evaluation_dimensions": ["overreach", "persona_precision"]},
    [msg("m_1", "我今天吃了火锅"), msg("m_2", "火锅真好吃"), msg("m_3", "周末又想去吃火锅")],
    expected_p={"traits": []},
    expected_m={"preferences": ["火锅"]},
    expected_neg={"traits": ["吃货人格", "贪吃"] + NEG_COMMON},
    anns=[])

# case_012 不同时间同属性变化（re-emphasize evolution）
write_case("case_012",
    {"name_or_alias": "小明", "tags": ["temporal-evolution"], "difficulty": "hard",
     "evaluation_dimensions": ["temporal_accuracy"]},
    [msg("m_1", "以前我最喜欢熬夜打游戏", sent="2021-01-01T00:00:00"),
     msg("m_2", "现在我每天十点就睡", sent="2024-01-01T00:00:00")],
    expected_p={"traits": []},
    expected_m={},
    expected_neg={"traits": []},
    anns=[])

# case_013 correction（build 后由 runner 侧测试，此处 messages 无 correction；标注 correction 维度）
write_case("case_013",
    {"name_or_alias": "小明", "tags": ["correction"], "difficulty": "hard",
     "evaluation_dimensions": ["correction_accuracy"]},
    [msg("m_1", "她说：我最喜欢喝奶茶", sent="2024-01-01T00:00:00")],
    expected_p={"traits": []},
    expected_m={"preferences": ["喜欢喝奶茶"]},
    expected_neg={"traits": []},
    anns=[])

# case_014 非法/错误 LLM interpretation 不在 messages 层（mock 固定正确）→ 标注为 component-only
write_case("case_014",
    {"name_or_alias": "小明", "tags": ["component-mock"], "difficulty": "easy",
     "evaluation_dimensions": ["determinism"]},
    [msg("m_1", "她总发哈哈哈哈"), msg("m_2", "她总发哈哈哈哈")],
    expected_p={"traits": []},
    expected_m={},
    expected_neg={"traits": []},
    anns=[])

print("generated 14 cases")
