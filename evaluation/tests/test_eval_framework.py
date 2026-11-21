#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 5.6 Evaluation Framework 自身测试。

覆盖：case schema 校验、annotation 校验、AUTO metric、provenance、determinism、
negative/conflict/temporal/correction、report 聚合、before/after、损坏 case、
缺 annotation、重复 case、冻结 SHA-1 校验。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
EVAL = os.path.dirname(HERE)
for p in (EVAL, os.path.join(os.path.dirname(EVAL), "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

import eval_schema  # noqa: E402
import eval_runner as er  # noqa: E402
import eval_llm_mocks as mocks  # noqa: E402
import persona_memory_builder as _pmb  # noqa: E402
import datetime as _dt  # noqa: E402

# 墙钟时间在确定性比较中的处理
# ----------------------------
# persona_memory_builder 用 datetime.now() 写 created_at / updated_at（秒级精度）。
# eval_runner 的确定性检查是对两次 run_chain 的结果逐字节比较
# （eval_runner.py 的 "determinism: 重复运行" 段），属冻结代码，
# 测试侧无法介入那次比较。两次运行一旦跨过整秒，就会被判为"不确定"，
# 造成本文件多条断言偶发失败。
#
# 处理方式：在测试进程内把 builder 的 now() 固定住——等价于"比较前把两边的
# created_at / updated_at 统一替换成同一个固定值"。测试自己做的比较则用
# _strip_wall_clock() 显式忽略这两个字段。
_WALL_CLOCK_FIXED = _dt.datetime(2026, 1, 1, 0, 0, 0)
_WALL_CLOCK_KEYS = ("created_at", "updated_at")
_WALL_CLOCK_SENTINEL = "<fixed>"


class _FrozenDatetime(_dt.datetime):
    """datetime.now() 恒返回同一时刻。"""

    @classmethod
    def now(cls, tz=None):
        return _WALL_CLOCK_FIXED


def _freeze_wall_clock() -> None:
    _pmb.datetime = _FrozenDatetime


def _strip_wall_clock(obj):
    """递归把 created_at / updated_at 替换为固定值（测试侧比较用）。"""
    if isinstance(obj, dict):
        return {k: (_WALL_CLOCK_SENTINEL if k in _WALL_CLOCK_KEYS else _strip_wall_clock(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip_wall_clock(v) for v in obj]
    return obj


def _canonical(pm) -> str:
    return json.dumps(_strip_wall_clock(pm), ensure_ascii=False, sort_keys=True)



class C:
    ok_n = 0
    fail_n = 0
    fails = []

    @classmethod
    def ok(cls, name, cond, detail=""):
        if cond:
            cls.ok_n += 1
        else:
            cls.fail_n += 1
            cls.fails.append(name + (f" — {detail}" if detail else ""))
            print(f"FAIL {name} {detail}")


def _mk_case(tmp, name="c_x", messages=None, meta=None, expected_p=None,
             expected_neg=None, anns=None):
    d = os.path.join(tmp, name)
    os.makedirs(d, exist_ok=True)
    if messages is None:
        messages = [{"id": "m_1", "content_fingerprint": "f1", "sequence": 0,
                     "sent_at": "2024-01-01T00:00:00", "sent_at_raw": "2024-01-01 00:00:00",
                     "sender": {"role": "target", "name": "小明", "sender_key": "小明"},
                     "content_type": None, "body": "我喜欢猫", "media": None,
                     "reply_to_message_id": None, "is_recalled": None, "in_group_chat": None}]
    ci = {"schema_version": "1.2", "platform": "wechat", "source_format": "txt",
          "source_ref": "x", "conversation_title": "小明", "default_sender_role": "unknown",
          "participants": [
              {"role": "user", "account_id": None, "names": ["我"], "match_method": "name_exact",
               "confidence": 0.85, "confirmed": True},
              {"role": "target", "account_id": None, "names": ["小明"], "match_method": "name_exact",
               "confidence": 0.9, "confirmed": True}],
          "messages": messages}
    json.dump(ci, open(os.path.join(d, "messages.json"), "w", encoding="utf-8"), ensure_ascii=False)
    meta = meta or {"case_id": name, "tags": ["t"], "difficulty": "easy",
                    "evaluation_dimensions": ["d"], "name_or_alias": "小明"}
    json.dump(meta, open(os.path.join(d, "meta.json"), "w", encoding="utf-8"), ensure_ascii=False)
    if expected_p is not None:
        json.dump(expected_p, open(os.path.join(d, "expected_persona.json"), "w", encoding="utf-8"), ensure_ascii=False)
    if expected_neg is not None:
        json.dump(expected_neg, open(os.path.join(d, "expected_negative.json"), "w", encoding="utf-8"), ensure_ascii=False)
    if anns is not None:
        json.dump(anns, open(os.path.join(d, "annotations.json"), "w", encoding="utf-8"), ensure_ascii=False)
    return d


def t_case_schema_valid():
    tmp = tempfile.mkdtemp()
    d = _mk_case(tmp, "case_good")
    C.ok("case-schema: valid case no problems", eval_schema.validate_case_dir(d) == [])
    C.ok("case-schema: valid meta", eval_schema.validate_meta(eval_schema.load_meta(d)) == [])
    shutil.rmtree(tmp)


def t_case_schema_missing():
    tmp = tempfile.mkdtemp()
    os.makedirs(os.path.join(tmp, "bad"))
    C.ok("case-schema: missing messages flagged", eval_schema.validate_case_dir(os.path.join(tmp, "bad")) != [])
    shutil.rmtree(tmp)


def t_case_schema_bad_json():
    tmp = tempfile.mkdtemp()
    d = os.path.join(tmp, "bad2"); os.makedirs(d)
    open(os.path.join(d, "messages.json"), "w").write("{ not json")
    json.dump({"case_id": "bad2"}, open(os.path.join(d, "meta.json"), "w"))
    probs = eval_schema.validate_case_dir(d)
    C.ok("case-schema: bad JSON flagged", any("JSON" in p for p in probs), str(probs))
    shutil.rmtree(tmp)


def t_annotation_valid():
    tmp = tempfile.mkdtemp()
    d = _mk_case(tmp, "cann", anns=[
        {"target": {"kind": "memory_item", "memoryItem_id": "mi_1", "bucket": "preferences", "value": "喜欢猫"},
         "evidence_support": "SUPPORTED", "target_placement": "memory", "overreach": False,
         "inference_quality": "direct", "confidence_rating": "reasonable", "provenance_complete": True}])
    C.ok("annotation: valid", eval_schema.validate_annotations(d) == [])
    shutil.rmtree(tmp)


def t_annotation_invalid():
    tmp = tempfile.mkdtemp()
    d = _mk_case(tmp, "cann2", anns=[
        {"target": {"kind": "memory_item", "memoryItem_id": "mi_1"},
         "evidence_support": "MAYBE", "target_placement": "nope", "overreach": False,
         "inference_quality": "magic", "confidence_rating": "???"}])
    errs = eval_schema.validate_annotations(d)
    C.ok("annotation: invalid enum flagged", len(errs) >= 1, str(errs))
    shutil.rmtree(tmp)


def t_auto_metrics():
    tmp = tempfile.mkdtemp()
    d = _mk_case(tmp, "cm", messages=[
        {"id": "m_1", "content_fingerprint": "f1", "sequence": 0, "sent_at": "2024-01-01T00:00:00",
         "sent_at_raw": "2024-01-01 00:00:00",
         "sender": {"role": "target", "name": "小明", "sender_key": "小明"},
         "content_type": None, "body": "我特别讨厌下雨", "media": None,
         "reply_to_message_id": None, "is_recalled": None, "in_group_chat": None}])
    r = er.run_case(d, repeat=2)
    C.ok("auto: schema_valid", r["auto"]["schema_valid"], str(r.get("errors")))
    C.ok("auto: deterministic", r["auto"]["deterministic"])
    C.ok("auto: provenance", r["auto"]["provenance"])
    shutil.rmtree(tmp)


def t_provenance_calculation():
    # 构造带非法 evidence 的 pm → provenance 检测应失败
    pm = {"schema_version": "1.2", "revision": 1,
          "persona": {"layer0_rules": {"do_not_say": [], "specific_edges": [], "reality_boundary": None},
                      "identity": {"name_or_alias": {"claim_id": "pc_x", "value": "小明",
                                                     "evidence_ids": [], "confidence": 1.0,
                                                     "basis": "user_report_only"}, "relationship": {}},
                      "speech_style": {"catchphrases": [], "examples": []},
                      "emotional_pattern": {}, "relationship_behavior": {}},
          "memory": {b: [] for b in er.pmb.MEMORY_BUCKETS}, "corrections": []}
    ok, probs = er.auto_provenance(pm, {})
    C.ok("provenance: empty-evidence name passes", ok)
    pm["persona"]["identity"]["occupation"] = {"claim_id": "pc_y", "value": "工程师",
                                               "evidence_ids": ["c_ghost"], "confidence": 0.9,
                                               "basis": "direct_quote"}
    ok2, probs2 = er.auto_provenance(pm, {})
    C.ok("provenance: ghost evidence flagged", (not ok2) and any("c_ghost" in p for p in probs2), str(probs2))


def t_determinism():
    tmp = tempfile.mkdtemp()
    # 无时间 → 极性相反且时间不可排序 → conflict（而非 temporal_evolution）
    d = _mk_case(tmp, "cdet", messages=[
        {"id": "m_1", "content_fingerprint": "f1", "sequence": 0, "sent_at": None, "sent_at_raw": None,
         "sender": {"role": "target", "name": "小明", "sender_key": "小明"},
         "content_type": None, "body": "我喜欢猫", "media": None,
         "reply_to_message_id": None, "is_recalled": None, "in_group_chat": None},
        {"id": "m_2", "content_fingerprint": "f2", "sequence": 1, "sent_at": None, "sent_at_raw": None,
         "sender": {"role": "target", "name": "小明", "sender_key": "小明"},
         "content_type": None, "body": "我讨厌猫", "media": None,
         "reply_to_message_id": None, "is_recalled": None, "in_group_chat": None}])
    ci = json.load(open(os.path.join(d, "messages.json"), encoding="utf-8"))
    outs = set()
    for _ in range(3):
        pm, _, errs = er.run_chain(ci, "小明")
        assert not errs, errs
        outs.add(_canonical(pm))
    C.ok("determinism: conflict case stable ×3", len(outs) == 1)
    # conflict: both pending + conflicts_with
    items = [it for b in pm["memory"].values() for it in b]
    C.ok("determinism: conflict keeps both pending", len(items) == 2 and all(i["status"] == "pending_confirmation" for i in items))
    C.ok("determinism: mutual conflicts_with", all(len(i["conflicts_with"]) == 1 for i in items))
    shutil.rmtree(tmp)


def t_negative_case():
    tmp = tempfile.mkdtemp()
    d = _mk_case(tmp, "cneg", messages=[
        {"id": "m_1", "content_fingerprint": "f1", "sequence": 0, "sent_at": None, "sent_at_raw": None,
         "sender": {"role": "target", "name": "小明", "sender_key": "小明"},
         "content_type": None, "body": "哈哈", "media": None,
         "reply_to_message_id": None, "is_recalled": None, "in_group_chat": None}],
        expected_neg={"traits": ["高冷", "回避型依恋", "控制欲"]})
    r = er.run_case(d, repeat=2)
    C.ok("negative: no overreach violation", r["auto"]["negative_violations"] == [],
         str(r["auto"]["negative_violations"]))
    shutil.rmtree(tmp)


def t_temporal_case():
    tmp = tempfile.mkdtemp()
    d = _mk_case(tmp, "ctemp", messages=[
        {"id": "m_1", "content_fingerprint": "f1", "sequence": 0, "sent_at": "2022-06-01T00:00:00",
         "sent_at_raw": "2022-06-01 00:00:00",
         "sender": {"role": "target", "name": "小明", "sender_key": "小明"},
         "content_type": None, "body": "2022年我喜欢喝奶茶", "media": None,
         "reply_to_message_id": None, "is_recalled": None, "in_group_chat": None},
        {"id": "m_2", "content_fingerprint": "f2", "sequence": 1, "sent_at": "2025-01-01T00:00:00",
         "sent_at_raw": "2025-01-01 00:00:00",
         "sender": {"role": "target", "name": "小明", "sender_key": "小明"},
         "content_type": None, "body": "2025年我已经不喝奶茶了", "media": None,
         "reply_to_message_id": None, "is_recalled": None, "in_group_chat": None}])
    pm, _, errs = er.run_chain(json.load(open(os.path.join(d, "messages.json"), encoding="utf-8")), "小明")
    assert not errs, errs
    prefs = pm["memory"]["preferences"]
    C.ok("temporal: container present", len(prefs) == 1 and prefs[0]["history"] is not None)
    C.ok("temporal: history has 2 slices", len(prefs[0]["history"]) == 2)
    C.ok("temporal: old preserved", "2022年我喜欢喝奶茶" in prefs[0]["history"][0]["value"])
    r = er.run_case(d, repeat=2)
    C.ok("temporal: auto problems none", r["auto"]["temporal_problems"] == [], str(r["auto"]["temporal_problems"]))
    shutil.rmtree(tmp)


def t_report_aggregate():
    tmp = tempfile.mkdtemp()
    d = _mk_case(tmp, "cagg", anns=[
        {"target": {"kind": "memory_item", "memoryItem_id": "mi_x", "value": "x"},
         "evidence_support": "SUPPORTED", "target_placement": "memory", "overreach": False,
         "inference_quality": "direct", "confidence_rating": "reasonable", "provenance_complete": True}])
    r = er.run_case(d, repeat=2)
    agg = er.aggregate_results([r])
    C.ok("report: aggregate count", agg["case_count"] == 1 and agg["annotated"] == 1)
    C.ok("report: evidence_fidelity computed", isinstance(agg.get("evidence_fidelity"), float))
    shutil.rmtree(tmp)


def t_before_after():
    tmp = tempfile.mkdtemp()
    d = _mk_case(tmp, "cb", anns=[
        {"target": {"kind": "memory_item", "memoryItem_id": "mi_x", "value": "x"},
         "evidence_support": "SUPPORTED", "target_placement": "memory", "overreach": False,
         "inference_quality": "direct", "confidence_rating": "reasonable", "provenance_complete": True}])
    r1 = {"aggregate": er.aggregate_results([er.run_case(d, repeat=2)])}
    r2 = {"aggregate": er.aggregate_results([er.run_case(d, repeat=2)])}
    import report
    comp = report.compare(r1, r2)
    C.ok("before-after: compare returns baseline/candidate/deltas",
         "baseline" in comp and "candidate" in comp and "deltas" in comp)
    C.ok("before-after: identical runs → zero delta",
         all((comp["deltas"][k] or 0) == 0 for k in comp["deltas"] if isinstance(comp["deltas"][k], (int, float))))
    shutil.rmtree(tmp)


def t_missing_annotation():
    tmp = tempfile.mkdtemp()
    d = _mk_case(tmp, "cnann")  # no annotations.json
    r = er.run_case(d, repeat=2)
    C.ok("missing-annotation: semantic None (not fake pass)", r["semantic"] is None)
    C.ok("missing-annotation: auto still runs", r["auto"]["deterministic"] is True)
    shutil.rmtree(tmp)


def t_duplicate_case_id():
    # runner 遍历目录，case 目录名需 case_*；重复目录只处理一次（不同名）。
    # 这里验证：同 messages 两个 case 目录各自独立跑不互扰。
    tmp = tempfile.mkdtemp()
    d1 = _mk_case(tmp, "case_dup1")
    d2 = _mk_case(tmp, "case_dup2")
    r1 = er.run_case(d1, repeat=1)
    r2 = er.run_case(d2, repeat=1)
    C.ok("duplicate: independent runs", r1["status"] == "PASS" and r2["status"] == "PASS")
    shutil.rmtree(tmp)


def t_frozen_sha():
    import hashlib
    expected = {"evidence_candidate.schema.json": "b679d69af1d0",
                "merge_group.schema.json": "aec7f85c0780",
                "resolved_evidence_bundle.schema.json": "b497d601bd75",
                "persona_memory.schema.json": "27750ee4ace4",
                "message.schema.json": "f0224e7a9697",
                "tools/evidence_extractor.py": "3c3063dbfe04",
                "tools/evidence_merge.py": "b42caa392f47",
                "tools/resolve_bundle.py": "543c00b59c0c",
                "tools/import_pipeline.py": "91178997bf4f"}
    sha = er.frozen_sha()
    C.ok("frozen-sha: all match", all((sha.get(f) or "")[:12] == v for f, v in expected.items()),
         str({f: (sha.get(f) or "")[:12] for f in expected if (sha.get(f) or "")[:12] != expected[f]}))


def t_dataset_end_to_end():
    # 跑真实 14-case dataset → 全过 + frozen 不变
    fb = er.frozen_sha()
    out = er.run_dataset(os.path.join(EVAL, "dataset"), repeat=2, frozen_before=fb)
    C.ok("e2e: 14 cases no ERROR", all(c["status"] != "ERROR" for c in out["cases"]))
    C.ok("e2e: all deterministic", all(c["auto"]["deterministic"] for c in out["cases"]))
    C.ok("e2e: frozen integrity", out["frozen_integrity_ok"])


def t_microdiff_stability():
    # LLM text micro-diff（标点/语气差异，语义相同）不得导致候选/记忆 ID 漂移
    # extractor canonical 去标点 → 两种措辞得到同 candidate_id → 同 memory id
    from evidence_extractor import canonicalize_claim, compute_candidate_id
    a = compute_candidate_id("target_message", "target", "她喜欢猫")
    b = compute_candidate_id("target_message", "target", "她喜欢猫。")
    c = compute_candidate_id("target_message", "target", "她喜欢猫～")
    C.ok("microdiff: 标点差异不改变 candidate_id", a == b == c, f"{a} {b} {c}")
    # 语义不同（但文字近）→ 不同（如加否定）→ 应区分（不误合并）
    d = compute_candidate_id("target_message", "target", "她不喜欢猫")
    C.ok("microdiff: 语义变化改变 candidate_id", a != d)
    # builder memory id 稳定性：同 bucket 同 canonical content 稳定
    import persona_memory_builder as pmb
    m1 = pmb.memory_item_id("preferences", "她喜欢猫")
    m2 = pmb.memory_item_id("preferences", "她喜欢猫")
    C.ok("microdiff: memory id stable for same content", m1 == m2)


def main():
    print("=== Evaluation Framework 测试 (Stage 5.6) ===")
    _freeze_wall_clock()
    tests = [
        ("case schema valid", t_case_schema_valid),
        ("case schema missing", t_case_schema_missing),
        ("case schema bad json", t_case_schema_bad_json),
        ("annotation valid", t_annotation_valid),
        ("annotation invalid", t_annotation_invalid),
        ("auto metrics", t_auto_metrics),
        ("provenance calculation", t_provenance_calculation),
        ("determinism + conflict", t_determinism),
        ("negative case", t_negative_case),
        ("temporal case", t_temporal_case),
        ("report aggregate", t_report_aggregate),
        ("before/after compare", t_before_after),
        ("missing annotation", t_missing_annotation),
        ("duplicate case", t_duplicate_case_id),
        ("frozen SHA-1", t_frozen_sha),
        ("dataset end-to-end", t_dataset_end_to_end),
        ("LLM micro-diff stability", t_microdiff_stability),
    ]
    for name, fn in tests:
        print(f"\n▶ {name}")
        try:
            fn()
        except Exception as e:
            import traceback
            C.ok(name, False, f"{type(e).__name__}: {e}")
            traceback.print_exc()
    print(f"\n通过 {C.ok_n} / 失败 {C.fail_n}")
    for f in C.fails:
        print("  -", f)
    sys.exit(0 if C.fail_n == 0 else 1)


if __name__ == "__main__":
    main()
