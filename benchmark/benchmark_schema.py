#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 5.8 Benchmark：稳定 result contract（非冻结，benchmark 自有）。"""

from __future__ import annotations

import json
from typing import Any, Dict

RESULT_VERSION = "1.0"

# AUTO 指标默认键（每项独立，不合成总分）
AUTO_KEYS = [
    "retrieval_precision", "retrieval_recall", "false_recall", "missed_relevant",
    "reality_conflict_detected", "uncertainty_behavior", "question_assertion_ok",
    "temporal_conflict_ok", "correction_overlay_ok", "correction_new_id_stable",
    "correction_evidence_preserved", "provenance_claims", "provenance_memory",
    "schema_valid", "deterministic_mock", "error_count",
]


def empty_run() -> Dict[str, Any]:
    return {
        "result_version": RESULT_VERSION,
        "run_id": None,
        "status": "PENDING",
        "provider": None,
        "model": None,
        "model_version": None,
        "configuration": {},
        "cases": [],
        "aggregate_auto_metrics": {},
        "human_metrics": None,
        "hybrid_metrics": None,
        "errors": [],
        "warnings": [],
        "privacy": {"raw_saved": False, "api_key_in_output": False},
    }


def empty_case_result() -> Dict[str, Any]:
    return {
        "case_id": None,
        "status": "PENDING",          # PASS / FAIL / ERROR / SKIPPED
        "provider": None,
        "model": None,
        "auto": {},
        "human": None,                # 人工标注占位
        "hybrid": None,
        "latency_ms": None,
        "usage": None,
        "response_ref": None,         # 默认不存 raw；存引用/hash
        "error": None,
    }


def save_run(run: Dict[str, Any], path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(run, f, ensure_ascii=False, indent=2)


def load_run(path: str) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)
