#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 5.6 Evaluation：case 与 annotation 的 schema 校验（框架内部，非产品数据契约）。

不校验冻结 schema（那些由各自模块负责）；这里只保证 golden case 结构与
annotations.json 满足 Evaluation 需要。
"""

from __future__ import annotations

import json
import os
from typing import Dict, List

CASE_REQUIRED_FILES = ["messages.json", "meta.json"]
OPTIONAL_FILES = ["expected_persona.json", "expected_memory.json",
                  "expected_negative.json", "annotations.json"]

VALID_TAGS = None  # 自由标签
VALID_EVIDENCE_SUPPORT = ["SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED",
                          "CONTRADICTED", "UNKNOWN"]
VALID_PLACEMENT = ["persona", "memory", "supporting_only", "should_not_exist"]
VALID_INFERENCE = ["direct", "reasonable_inference", "speculative", None]
VALID_CONFIDENCE = ["reasonable", "too_high", "too_low", "n/a"]


class CaseError(Exception):
    pass


def validate_case_dir(case_dir: str) -> List[str]:
    """返回缺失/损坏的文件列表（非空即 case 有 ERROR）。"""
    problems = []
    for f in CASE_REQUIRED_FILES:
        p = os.path.join(case_dir, f)
        if not os.path.exists(p):
            problems.append(f"missing required {f}")
            continue
        try:
            json.load(open(p, encoding="utf-8"))
        except json.JSONDecodeError as e:
            problems.append(f"{f} 不是合法 JSON: {e}")
    return problems


def load_meta(case_dir: str) -> dict:
    p = os.path.join(case_dir, "meta.json")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def validate_meta(meta: dict) -> List[str]:
    errs = []
    for k in ("case_id", "tags", "difficulty", "evaluation_dimensions"):
        if k not in meta:
            errs.append(f"meta 缺 {k}")
    if meta.get("case_id") is None or not isinstance(meta.get("case_id"), str):
        errs.append("case_id 必须为字符串")
    if not isinstance(meta.get("tags", []), list):
        errs.append("tags 必须为数组")
    if not isinstance(meta.get("evaluation_dimensions", []), list):
        errs.append("evaluation_dimensions 必须为数组")
    return errs


def _validate_annotation(a: dict, case_id: str) -> List[str]:
    errs = []
    target = a.get("target") or {}
    if not isinstance(target, dict):
        return ["annotation 缺 target 对象"]
    if target.get("kind") not in ("persona_claim", "memory_item"):
        errs.append(f"target.kind 非法: {target.get('kind')}")
    if not target.get("claim_id") and not target.get("memoryItem_id"):
        errs.append("target 缺 claim_id 或 memoryItem_id")
    es = a.get("evidence_support")
    if es not in VALID_EVIDENCE_SUPPORT:
        errs.append(f"evidence_support 非法: {es}（应为 {VALID_EVIDENCE_SUPPORT}）")
    pl = a.get("target_placement")
    if pl not in VALID_PLACEMENT:
        errs.append(f"target_placement 非法: {pl}（应为 {VALID_PLACEMENT}）")
    inf = a.get("inference_quality")
    if inf not in VALID_INFERENCE:
        errs.append(f"inference_quality 非法: {inf}")
    cr = a.get("confidence_rating")
    if cr not in VALID_CONFIDENCE:
        errs.append(f"confidence_rating 非法: {cr}")
    return errs


def validate_annotations(case_dir: str) -> List[str]:
    p = os.path.join(case_dir, "annotations.json")
    if not os.path.exists(p):
        return []   # 无标注 = 该 case 无 semantic 分（在报告中标记无标注），不算损坏
    meta = load_meta(case_dir)
    case_id = meta.get("case_id", os.path.basename(case_dir))
    try:
        anns = json.load(open(p, encoding="utf-8"))
    except json.JSONDecodeError as e:
        return [f"annotations.json 非法 JSON: {e}"]
    if not isinstance(anns, list):
        return ["annotations.json 顶层应为数组"]
    errs = []
    for i, a in enumerate(anns):
        if not isinstance(a, dict):
            errs.append(f"annotation[{i}] 非对象")
            continue
        errs += [f"annotation[{i}]: {e}" for e in _validate_annotation(a, case_id)]
    return errs


def expected_files(case_dir: str) -> Dict[str, dict]:
    """加载 expected_*.json（存在则返回 dict；缺则空 dict）。"""
    out = {}
    for f in ("expected_persona.json", "expected_memory.json", "expected_negative.json"):
        p = os.path.join(case_dir, f)
        if os.path.exists(p):
            out[f] = json.load(open(p, encoding="utf-8"))
        else:
            out[f] = {}
    return out
