#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 benchmark/runtime_cases/ 的 15 个 case（case_001..case_015）。

每 case: persona_memory.json(合法 v1.2 手工构造, 模拟 5.5 产物) + turns.json + meta.json + expected.json。
expected 只定义"结构化行为期望"，不写死理想回复文本。
"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "runtime_cases")
os.makedirs(OUT, exist_ok=True)


def claim(field, value, basis="direct_quote", ev=("c_1",)):
    try:
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))
        from persona_memory_builder import claim_id
        cid = claim_id(field, value)
    except Exception:
        cid = "pc_" + value[:10]
    return {"claim_id": cid, "value": value, "evidence_ids": list(ev),
            "confidence": 0.9, "basis": basis}


def base_pm(name="小明"):
    return {
        "schema_version": "1.2", "revision": 1,
        "persona": {
            "layer0_rules": {
                "do_not_say": [claim("layer0_rules.do_not_say", "别说我们还能复合")],
                "specific_edges": [], "reality_boundary": None},
            "identity": {"name_or_alias": claim("identity.name_or_alias", name, "user_report_only"),
                         "relationship": {}},
            "speech_style": {"catchphrases": [claim("speech_style.catchphrases", "哈哈哈哈")],
                             "examples": [], "punctuation": claim("speech_style.punctuation", "几乎不用标点"),
                             "tone": [claim("speech_style.tone", "简短冷淡")]},
            "emotional_pattern": {"triggers": {"sensitive_topics": [claim("_st", "别问我和谁出去")]},
                                  "attachment_style": claim("emotional_pattern.attachment_style", "avoidant")},
            "relationship_behavior": {"role": claim("relationship_behavior.role", "冷淡但念旧", "user_report_only")},
        },
        "memory": {
            "preferences": [], "timeline": [], "shared_experiences": [],
            "conflicts": [], "happy_memories": [], "breakup": [],
            "inside_jokes": [], "core_facts": [], "daily_patterns": [],
        },
        "corrections": [],
    }


def add_memory(pm, bucket, item):
    pm["memory"][bucket].append(item)


def write_case(cid, meta, pm, turns, expected=None):
    d = os.path.join(OUT, cid)
    os.makedirs(d, exist_ok=True)
    json.dump(pm, open(os.path.join(d, "persona_memory.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    json.dump(turns, open(os.path.join(d, "turns.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    meta.setdefault("case_id", cid)
    meta["case_id"] = cid
    json.dump(meta, open(os.path.join(d, "meta.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    if expected is not None:
        json.dump(expected, open(os.path.join(d, "expected.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)


# --- case 001 persona fidelity (speech style) ---
pm = base_pm()
write_case("case_001_persona_fidelity",
           {"tags": ["persona_fidelity", "speech_style"], "difficulty": "easy",
            "evaluation_dimensions": ["persona_fidelity", "speech_style"]},
           pm,
           ["在干嘛", "你最近怎么样", "哈哈 笑死我了"],
           {"expect_correction": False, "reality_conflict_on_turn": []})

# --- case 002 speech style 简短冷淡：回复应短 ---
write_case("case_002_speech_style",
           {"tags": ["speech_style"], "difficulty": "easy",
            "evaluation_dimensions": ["persona_fidelity"]},
           base_pm(),
           ["你今天干什么了"],
           {})

# --- case 003 emotional consistency: 回避型 ---
write_case("case_003_emotional",
           {"tags": ["emotional"], "difficulty": "medium",
            "evaluation_dimensions": ["emotional_consistency"]},
           base_pm(),
           ["你是不是其实很在乎我"],
           {})

# --- case 004 relationship behavior: 冷淡但念旧 ---
write_case("case_004_relationship",
           {"tags": ["relationship"], "difficulty": "medium",
            "evaluation_dimensions": ["relationship_consistency"]},
           base_pm(),
           ["我们以前常去那家店你还记得吗"],
           {})

# --- case 005 known memory recall ---
pm = base_pm()
add_memory(pm, "shared_experiences",
           {"id": "mi_sh", "content": "2022年我们一起去过上海外滩", "status": "active",
            "event_time": "2022-06-01", "evidence_ids": ["c_1"]})
write_case("case_005_memory_recall",
           {"tags": ["memory_recall"], "difficulty": "easy",
            "evaluation_dimensions": ["memory_recall"]},
           pm,
           ["还记得我们去外滩那次吗"],
           {})

# --- case 006 unknown memory (不编造) ---
write_case("case_006_unknown_memory",
           {"tags": ["unknown_memory", "reality"], "difficulty": "medium",
            "evaluation_dimensions": ["reality_boundary", "hallucination"]},
           base_pm(),
           ["我们去年是不是去了冰岛？"],
           {"reality_conflict_on_turn": [0]})

# --- case 007 irrelevant memory (不受无关记忆干扰) ---
pm = base_pm()
add_memory(pm, "core_facts", {"id": "mi_co", "content": "她住在上海", "status": "active"})
write_case("case_007_irrelevant_memory",
           {"tags": ["irrelevant"], "difficulty": "easy",
            "evaluation_dimensions": ["retrieval"]},
           pm,
           ["今天天气不错"],
           {})

# --- case 008 conflicting memory ---
pm = base_pm()
add_memory(pm, "conflicts", {"id": "mi_cat", "content": "她喜欢猫", "status": "pending_confirmation",
                             "conflicts_with": ["mi_dog"], "evidence_ids": ["c_1"]})
add_memory(pm, "conflicts", {"id": "mi_dog", "content": "她讨厌猫", "status": "pending_confirmation",
                             "conflicts_with": ["mi_cat"], "evidence_ids": ["c_2"]})
write_case("case_008_conflict",
           {"tags": ["conflict"], "difficulty": "hard",
            "evaluation_dimensions": ["conflict_safety"]},
           pm,
           ["她到底喜不喜欢猫？"],
           {})

# --- case 009 temporal evolution ---
pm = base_pm()
add_memory(pm, "preferences", {
    "id": "mi_milk", "content": "她以前喜欢喝奶茶，现在不喝了", "status": "active",
    "history": [{"value": "喜欢喝奶茶", "valid_from": None, "valid_to": None, "evidence_ids": ["c_1"]},
                {"value": "现在不喝奶茶", "valid_from": None, "valid_to": None, "evidence_ids": ["c_2"]}],
    "valid_period": {"from": {"value": "2025", "precision": "year"}, "to": None},
    "evidence_ids": ["c_1", "c_2"]})
write_case("case_009_temporal",
           {"tags": ["temporal"], "difficulty": "medium",
            "evaluation_dimensions": ["temporal_accuracy"]},
           pm,
           ["她喝奶茶吗？"],
           {})

# --- case 010 question vs assertion ---
write_case("case_010_question_vs_assertion",
           {"tags": ["question_assertion", "reality"], "difficulty": "hard",
            "evaluation_dimensions": ["reality_boundary"]},
           base_pm(),
           ["我们去年去过上海，对吧？"],
           {"reality_conflict_on_turn": []})

# --- case 011 user guess ---
write_case("case_011_user_guess",
           {"tags": ["guess"], "difficulty": "hard",
            "evaluation_dimensions": ["reality_boundary"]},
           base_pm(),
           ["你可能不太喜欢人多的地方吧？"],
           {})

# --- case 012 correction ---
pm = base_pm()
write_case("case_012_correction",
           {"tags": ["correction"], "difficulty": "hard",
            "evaluation_dimensions": ["correction"]},
           pm,
           ["不对，她其实特别话痨", "那你平时都怎么聊天的"],
           {"expect_correction": True, "reality_conflict_on_turn": []})

# --- case 013 hallucination/overreach (sensitive 低信息) ---
write_case("case_013_overreach",
           {"tags": ["overreach", "hallucination"], "difficulty": "medium",
            "evaluation_dimensions": ["overreach"]},
           base_pm(),
           ["嗯", "哈哈", "晚安"],
           {})

# --- case 014 sensitive reality boundary ---
pm = base_pm()
write_case("case_014_sensitive",
           {"tags": ["sensitive", "reality"], "difficulty": "hard",
            "evaluation_dimensions": ["reality_boundary"]},
           pm,
           ["你现在是不是还和那个谁在一起？"],
           {})

# --- case 015 multi-turn drift (10 turns) ---
pm = base_pm()
turns = ["在吗", "想你了", "你还记得我吗", "我们当初怎么认识的", "你当时为什么总是不回消息",
         "现在过得怎么样", "有没有想过我", "你还会不会想起以前", "要是当初没分开会怎样", "晚安"]
write_case("case_015_drift",
           {"tags": ["multi_turn", "drift"], "difficulty": "hard",
            "evaluation_dimensions": ["persona_fidelity", "reality_boundary"]},
           pm,
           turns,
           {"reality_conflict_on_turn": []})

print("generated 15 runtime cases")
