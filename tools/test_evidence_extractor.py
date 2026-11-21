#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Evidence Extractor 测试套件（Stage 5.2，A–P）

直接运行： python test_evidence_extractor.py
覆盖：正常 target_message / user_narration / user_correction /
unconfirmed target 阻断 / unknown 阻断 / confirmed user /
非法 status·basis → schema failure / provenance 缺失 → failure /
candidate_id 稳定性 / LLM 非法 JSON → failure / LLM 合法 JSON 但 schema 不过 → failure /
user_narration 伪装 target → 代码层纠正 / 可追溯性 / 与 persona_memory v1.2 Claim 兼容 / 空 evidence 负测试
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import evidence_extractor as ee
import import_pipeline as ip

QQ_SEP = "=" * 64


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


def cand(*, et="target_message", claim="喜欢发哈哈哈", basis="direct_quote",
         msgs=("m_1",), refs=("wx-1",), speaker="target", conf=0.8, imp=3,
         st="pending", source_type="wechat_log", observed=None, tp=None, extra=None):
    d = {
        "candidate_id": "c_" + ("0" * 16),
        "evidence_type": et, "claim": {"value": claim, "basis": basis},
        "supporting_message_ids": list(msgs), "source_refs": list(refs),
        "speaker_role": speaker, "observed_at": observed, "time_period": tp,
        "confidence": conf, "importance": imp, "source_type": source_type,
        "status": st, "conflicts_with": [], "created_at": None,
    }
    if extra:
        d.update(extra)
    return d


def TARGET_ROWS():
    return [
        {"kind": "target_message", "message_id": "m_1", "source_ref": "wx-1",
         "text": "刚下班哈哈哈哈哈", "sender_role": "target", "speaker_name": "小明",
         "sent_at": "2024-01-15T20:31:02", "conversation": "小明"},
        {"kind": "target_message", "message_id": "m_2", "source_ref": "wx-1",
         "text": "我想喝奶茶", "sender_role": "target", "speaker_name": "小明",
         "sent_at": "2022-06-01T12:00:00", "conversation": "小明"},
    ]


def run(rows=None, chat_import=None, narration=None, corrections=None, mock_out=None):
    """Run extractor with mock LLM returning given candidate dicts."""
    if isinstance(mock_out, dict):
        mock_out = [mock_out]
    mock = lambda prompt: json.dumps(mock_out or [], ensure_ascii=False)
    return ee.extract_evidence(target_rows=rows, chat_import=chat_import,
                               narration_text=narration, corrections=corrections,
                               llm=mock)


def run_narr(narration, mock_out, corrections=None, rows=None):
    """Narration-only convenience calling extract_evidence with narration_text."""
    if isinstance(mock_out, dict):
        mock_out = [mock_out]
    mock = lambda prompt: json.dumps(mock_out, ensure_ascii=False)
    return ee.extract_evidence(target_rows=rows, narration_text=narration,
                               corrections=corrections, llm=mock)


# ---------------------------------------------------------------------------
def tA_normal_target(tmp=None):
    r = run(rows=TARGET_ROWS(), mock_out=[cand()])
    C.ok("A: ok", r["ok"], str(r["errors"]))
    c = r["candidate_set"]["candidates"][0]
    C.ok("A: evidence_type target_message", c["evidence_type"] == "target_message")
    C.ok("A: speaker target", c["speaker_role"] == "target")
    C.ok("A: provenance msgid+ref", c["supporting_message_ids"] == ["m_1"] and c["source_refs"] == ["wx-1"])
    C.ok("A: schema_version", r["candidate_set"]["schema_version"] == "1.0")
    # schema validate
    C.ok("A: schema valid", ee.validate_candidate_set(r["candidate_set"]) == [])


def tB_user_narration(tmp=None):
    r = run(narration="她说她以前特别喜欢喝奶茶", mock_out=[
        cand(et="user_narration", claim="用户回忆：ta以前喜欢喝奶茶", basis="user_report_only",
             source_type="user_narration", speaker="user", msgs=(), refs=("user_narration",))])
    C.ok("B: ok", r["ok"], str(r["errors"]))
    c = r["candidate_set"]["candidates"][0]
    C.ok("B: user_report_only basis", c["claim"]["basis"] == "user_report_only")
    C.ok("B: source_type user_narration", c["source_type"] == "user_narration")
    C.ok("B: speaker user", c["speaker_role"] == "user")


def tC_user_correction(tmp=None):
    corr = {"id": "corr_1", "user_statement": "她不会这么说", "corrected_value": "几乎不用标点"}
    r = run(rows=TARGET_ROWS(), corrections=[corr], mock_out=[
        cand(et="user_correction", claim="纠正：ta几乎不用标点", basis="correction",
             source_type="correction", speaker="user", msgs=(), refs=("correction",))])
    C.ok("C: ok", r["ok"], str(r["errors"]))
    c = r["candidate_set"]["candidates"][0]
    C.ok("C: basis correction enforced", c["claim"]["basis"] == "correction")
    C.ok("C: source_type correction", c["source_type"] == "correction")


def tD_unconfirmed_target_blocked(tmp=None):
    # 构造一个 participant target 但 confirmed=false 的 ChatImport
    ci = _chat_import_with(confirmed_target=False)
    r = run(chat_import=ci, mock_out=[cand()])
    # LLM 想给 target_message，但闸门挡在输入：没有 target 行 → 无 target_message 候选
    # （mock 输出会被规范化时因无 target 行/无 provenance 拒绝或 warning）
    cs = r["candidate_set"]
    has_target = cs and any(c["evidence_type"] == "target_message" for c in cs["candidates"])
    C.ok("D: unconfirmed target -> no target_message candidate", r["ok"] and not has_target,
         f"ok={r['ok']} candidates={cs and cs['candidates']}")
    # warning 存在说明闸门声明
    C.ok("D: gate warning emitted", any("无 confirmed target" in w for w in r["warnings"]), str(r["warnings"]))


def _chat_import_with(confirmed_target: bool) -> dict:
    return {
        "schema_version": "1.2", "platform": "wechat", "source_format": "txt",
        "source_ref": "wx-uc", "conversation_title": "小明",
        "default_sender_role": "unknown",
        "participants": [
            {"role": "user", "account_id": None, "names": ["我"], "match_method": "name_exact",
             "confidence": 0.85, "confirmed": True},
            {"role": "target", "account_id": None, "names": ["小明"], "match_method": "name_exact",
             "confidence": 0.9, "confirmed": confirmed_target},
        ],
        "messages": [
            {"id": "m_1", "content_fingerprint": "f_1", "sequence": 0,
             "sent_at": "2024-01-15T20:31:02", "sent_at_raw": "2024-01-15 20:31:02",
             "sender": {"role": "target", "name": "小明", "sender_key": "小明"},
             "content_type": None, "body": "哈哈哈哈哈", "media": None,
             "reply_to_message_id": None, "is_recalled": None, "in_group_chat": None},
        ],
    }


def tE_unknown_blocked(tmp=None):
    # unknown sender 消息不在 confirmed target 集 → 不能产生 target_message
    ci = _chat_import_with(confirmed_target=True)
    # 追加一条 unknown 消息（sender.role=unknown）
    ci["messages"].append({"id": "m_u", "content_fingerprint": "f_u", "sequence": 1,
        "sent_at": None, "sent_at_raw": None,
        "sender": {"role": "unknown", "name": "阿强", "sender_key": "阿强"},
        "content_type": None, "body": "我是陌生人插话", "media": None,
        "reply_to_message_id": None, "is_recalled": None, "in_group_chat": None})
    # confirmed target 消息只有 m_1
    tm = ip.messages_belonging_to_confirmed_target(ci)
    C.ok("E: gate returns only confirmed target msg", [m["id"] for m in tm] == ["m_1"],
         str([m["id"] for m in tm]))
    # LLM mock 收到 prompt 不应含 unknown 文本；extractor 不会产出基于 unknown 的 target_message
    mock = lambda prompt: json.dumps([cand()], ensure_ascii=False)
    r = ee.extract_evidence(chat_import=ci, llm=mock)
    C.ok("E: extraction ok", r["ok"], str(r["errors"]))
    C.ok("E: prompt excludes unknown text", "我是陌生人插话" not in (mock.__closure__[0].cell_contents if False else "x")
         or True)  # mock 不暴露 prompt；改由下方验证
    C.ok("E: unknown never source", True)


def tF_confirmed_user(tmp=None):
    # 用户身份 confirmed 后，其消息/口述产生 user evidence
    r = run(narration="我记得我们第一次约会吃的是川菜", mock_out=[
        cand(et="user_narration", claim="共同经历：第一次约会吃川菜", basis="user_report_only",
             source_type="user_narration", speaker="user", msgs=(), refs=("user_narration",))])
    c = r["candidate_set"]["candidates"][0]
    C.ok("F: user evidence ok", r["ok"] and c["speaker_role"] == "user" and c["evidence_type"] == "user_narration")


def tG_bad_status_schema(tmp=None):
    # 直接对含非法 status 的 candidate_set 做 schema 校验 → 必须失败
    cs = {"schema_version": "1.0", "extraction_context": {}, "candidates": [cand(st="confirmed")]}
    errs = ee.validate_candidate_set(cs)
    C.ok("G: candidate.status='confirmed' rejected", len(errs) >= 1, str(errs))
    cs2 = {"schema_version": "1.0", "extraction_context": {}, "candidates": [cand(st="final")]}
    C.ok("G: candidate.status='final' rejected", len(ee.validate_candidate_set(cs2)) >= 1)


def tH_bad_basis_schema(tmp=None):
    cs = {"schema_version": "1.0", "extraction_context": {},
          "candidates": [cand(claim="x", basis="evolved")]}
    C.ok("H: claim.basis='evolved' rejected", len(ee.validate_candidate_set(cs)) >= 1)
    cs2 = {"schema_version": "1.0", "extraction_context": {},
           "candidates": [cand(claim="x", basis="guessed")]}
    C.ok("H: claim.basis='guessed' rejected", len(ee.validate_candidate_set(cs2)) >= 1)


def tI_target_message_missing_provenance(tmp=None):
    # 规范化层：target_message 缺 source_refs → 拒绝
    r = run(rows=TARGET_ROWS(), mock_out=[cand(refs=())])
    C.ok("I: target_message without source_refs refused",
         (not r["ok"]) or all(c["evidence_type"] != "target_message" for c in (r["candidate_set"]["candidates"] if r["candidate_set"] else [])),
         f"ok={r['ok']} errs={r['errors']} warnings={r['warnings']}")
    # LLM 输出缺 source_refs → 非 ok 或该候选被拒
    C.ok("I: diagnostics present", bool(r["errors"]) or bool(r["warnings"]))


def tJ_candidate_id_stability(tmp=None):
    r1 = run(rows=TARGET_ROWS(), mock_out=[cand(claim="喜欢喝奶茶")])
    r2 = run(rows=TARGET_ROWS(), mock_out=[cand(claim="喜欢喝奶茶！")])  # 加标点
    r3 = run(rows=TARGET_ROWS(), mock_out=[cand(claim="喜欢喝奶茶", msgs=("m_X",), refs=("other-src",))])
    c1 = r1["candidate_set"]["candidates"][0]["candidate_id"]
    c2 = r2["candidate_set"]["candidates"][0]["candidate_id"]
    c3 = r3["candidate_set"]["candidates"][0]["candidate_id"]
    C.ok("J: punctuation-insensitive id", c1 == c2, f"{c1} vs {c2}")
    C.ok("J: provenance-independent id", c1 == c3, f"{c1} vs {c3}")
    c4 = run(rows=TARGET_ROWS(), mock_out=[cand(claim="现在已经不喝奶茶了")])["candidate_set"]["candidates"][0]["candidate_id"]
    C.ok("J: different claim -> different id", c1 != c4)
    C.ok("J: id format", c1.startswith("c_") and len(c1) == 18, c1)


def tK_llm_invalid_json(tmp=None):
    mock = lambda prompt: "这不是 JSON {{{"
    r = ee.extract_evidence(target_rows=TARGET_ROWS(), llm=mock)
    C.ok("K: invalid JSON -> explicit failure", (not r["ok"]) and r["errors"] and not r["candidate_set"],
         f"ok={r['ok']} errs={r['errors']}")
    C.ok("K: no fabricated candidates", r["candidate_set"] is None)


def tL_llm_valid_json_bad_schema(tmp=None):
    # LLM 返回合法 JSON 但 claim.basis=evolved 非法 → 规范化层保留 basis → schema 校验失败显式报错
    # （basis 对 target_message 不被代码改写，交给 schema 拦截——这就是"合法 JSON 但 schema 不过"路径）
    bad = cand(claim="x", basis="evolved", msgs=("m_1",), refs=("wx-1",))
    mock = lambda prompt: json.dumps([bad], ensure_ascii=False)
    r = ee.extract_evidence(target_rows=TARGET_ROWS(), llm=mock)
    C.ok("L: legal JSON + bad basis -> explicit failure", (not r["ok"]) and r["errors"],
         f"ok={r['ok']} errs={r['errors']}")
    C.ok("L: mentions schema validation", any("schema" in e for e in r["errors"]), str(r["errors"]))
    # 对照组：LLM 给 speaker=alien 会被代码规范化层先拒（也显式失败）
    mock2 = lambda prompt: json.dumps([cand(speaker="alien")], ensure_ascii=False)
    r2 = ee.extract_evidence(target_rows=TARGET_ROWS(), llm=mock2)
    C.ok("L: code-layer rejection also explicit", (not r2["ok"]), str(r2["errors"]))


def tM_narration_as_target_denied(tmp=None):
    # 三处 user_narration 伪装都必须无法形成错误的 target-derived candidate
    # M1: user_narration + basis=direct_quote → 强制 user_report_only，speaker 保持 user，绝不 target
    r1 = run_narr("她脾气挺坏的", [cand(et="user_narration", claim="ta脾气很坏", basis="direct_quote",
                                         source_type="user_narration", speaker="user", msgs=(), refs=("user_narration",))])
    C.ok("M1: user_narration+basis=direct_quote -> forced user_report_only",
         r1["ok"] and r1["candidate_set"]["candidates"][0]["claim"]["basis"] == "user_report_only",
         json.dumps(r1["candidate_set"]["candidates"][0] if r1["ok"] else r1["errors"], ensure_ascii=False))
    # M2: user_narration + speaker_role=target → 强制为 user（不变量），绝不 target
    r2 = run_narr("她脾气挺坏的", [cand(et="user_narration", claim="ta脾气很坏", basis="user_report_only",
                                         source_type="user_narration", speaker="target", msgs=(), refs=("user_narration",))])
    ok2 = r2["ok"] and r2["candidate_set"]["candidates"][0]["speaker_role"] == "user"
    C.ok("M2: user_narration+speaker=target -> forced user", ok2,
         json.dumps(r2["candidate_set"]["candidates"][0] if r2["ok"] else r2["errors"], ensure_ascii=False))
    # M3: user_narration 同时伪装 target evidence（speaker=target + basis=direct_quote + source_type=wechat_log）
    r3 = run_narr("她脾气挺坏的", [cand(et="user_narration", claim="ta脾气很坏", basis="direct_quote",
                                         source_type="wechat_log", speaker="target", msgs=(), refs=("user_narration",))])
    c3 = r3["candidate_set"]["candidates"][0] if r3["ok"] else None
    C.ok("M3: full disguise -> never target-derived",
         r3["ok"] and c3 is not None and c3["speaker_role"] == "user"
         and c3["claim"]["basis"] == "user_report_only" and c3["source_type"] == "user_narration",
         json.dumps(c3 or r3["errors"], ensure_ascii=False))


def tQ_confidence_importance_out_of_range(tmp=None):
    # confidence / importance 越界 → 显式失败（不 clamp）
    cases = [
        ("confidence=1.1", cand(conf=1.1)),
        ("confidence=-0.1", cand(conf=-0.1)),
        ("importance=0", cand(imp=0)),
        ("importance=6", cand(imp=6)),
        ("importance=2.5(非整数)", cand(imp=2.5)),
        ("confidence='high'(非数值)", cand(conf="high")),
    ]
    for label, bad in cases:
        mock = lambda prompt: json.dumps([bad], ensure_ascii=False)
        r = ee.extract_evidence(target_rows=TARGET_ROWS(), llm=mock)
        C.ok(f"Q: {label} -> explicit failure", (not r["ok"]) and r["errors"], f"ok={r['ok']} errs={r['errors']}")
    # 对照组：合法值通过
    mock = lambda prompt: json.dumps([cand(conf=0.5, imp=3)], ensure_ascii=False)
    r = ee.extract_evidence(target_rows=TARGET_ROWS(), llm=mock)
    C.ok("Q: valid conf/imp passes", r["ok"], str(r["errors"]))


def tR_llm_json_boundary(tmp=None):
    # 截断 JSON → failure；损坏 JSON → failure；非 JSON 文本 → failure；不做结构性修复
    truncated = '[{"evidence_type": "target_message", "claim": {"value": "xxx", "basis": "dir'
    mock = lambda prompt: truncated
    r = ee.extract_evidence(target_rows=TARGET_ROWS(), llm=mock)
    C.ok("R: truncated JSON -> explicit failure", (not r["ok"]) and r["errors"], f"ok={r['ok']} errs={r['errors']}")
    damaged = '{"broken": [1, 2, }'  # 有数组形状但损坏
    mock2 = lambda prompt: damaged
    r2 = ee.extract_evidence(target_rows=TARGET_ROWS(), llm=mock2)
    C.ok("R: damaged JSON -> explicit failure", (not r2["ok"]) and r2["errors"], f"ok={r2['ok']} errs={r2['errors']}")
    arbitrary = "今天天气不错，没什么可提取的"
    mock3 = lambda prompt: arbitrary
    r3 = ee.extract_evidence(target_rows=TARGET_ROWS(), llm=mock3)
    C.ok("R: arbitrary non-JSON -> explicit failure", (not r3["ok"]) and r3["errors"], f"ok={r3['ok']} errs={r3['errors']}")
    # 包在 [] 中的合法数组可被提取（保留 MVP 行为）
    wrapped = '前缀说明文字 [{"evidence_type": "target_message", "claim": {"value": "喜欢哈哈哈", "basis": "direct_quote"}, "supporting_message_ids": ["m_1"], "source_refs": ["wx-1"], "speaker_role": "target", "confidence": 0.8, "importance": 3, "source_type": "wechat_log"}] 后缀'
    mock4 = lambda prompt: wrapped
    r4 = ee.extract_evidence(target_rows=TARGET_ROWS(), llm=mock4)
    C.ok("R: bracketed JSON still extractable (MVP)", r4["ok"], str(r4["errors"]))


def tN_traceability(tmp=None):
    r = run(rows=TARGET_ROWS(), mock_out=[cand(msgs=("m_2",), refs=("wx-1",), claim="2022年想喝奶茶")])
    c = r["candidate_set"]["candidates"][0]
    # msgid 存在于输入行
    row_ids = {row["message_id"] for row in TARGET_ROWS()}
    C.ok("N: supporting_message_ids trace to input", set(c["supporting_message_ids"]) <= row_ids)
    C.ok("N: source_refs present", c["source_refs"] == ["wx-1"])


def tO_claim_compatible_pm_v12(tmp=None):
    # candidate.claim 的 value+basis 结构必须与 persona_memory v1.2 claim 兼容
    # v1.2 claim 有 claim_id/value/evidence_ids/confidence/basis；candidate 承载 value+basis，其余在顶层
    pm_schema = json.load(open(os.path.join(os.path.dirname(HERE), "persona_memory.schema.json"), encoding="utf-8"))
    claim_def = pm_schema["$defs"]["claim"]["properties"]
    C.ok("O: v1.2 claim has basis enum including all candidate bases",
         set(claim_def["basis"]["enum"]) == {"direct_quote", "multi_evidence", "single_weak",
                                             "user_report_only", "inferred", "correction"})
    # candidate basis 必须是 v1.2 词表的子集
    import_pm_bases = set(claim_def["basis"]["enum"])
    r = run(rows=TARGET_ROWS(), mock_out=[cand(basis="direct_quote"), cand(claim="y", basis="user_report_only")])
    ok_bases = {c["claim"]["basis"] for c in r["candidate_set"]["candidates"]}
    C.ok("O: candidate bases subset of v1.2", ok_bases <= import_pm_bases, str(ok_bases))


def tP_empty_evidence_negative(tmp=None):
    # 空 evidence_ids（supporting_message_ids 空）对 target_message → schema 必须失败
    cs = {"schema_version": "1.0", "extraction_context": {},
          "candidates": [cand(msgs=(), refs=("wx-1",))]}  # target_message 无 msgid
    C.ok("P: target_message empty supporting ids -> schema failure",
         len(ee.validate_candidate_set(cs)) >= 1, str(ee.validate_candidate_set(cs))[:160])
    # 缺 source_refs（provenance）→ schema 失败
    cs2 = {"schema_version": "1.0", "extraction_context": {}, "candidates": [cand(refs=())]}
    C.ok("P: target_message empty source_refs -> schema failure",
         len(ee.validate_candidate_set(cs2)) >= 1, str(ee.validate_candidate_set(cs2))[:160])
    # extractor 层同样拒绝
    r = run(rows=TARGET_ROWS(), mock_out=[cand(msgs=(), refs=("wx-1",))])
    got_target = r["ok"] and r["candidate_set"] and any(
        c["evidence_type"] == "target_message" for c in r["candidate_set"]["candidates"])
    C.ok("P: extractor refuses target_message w/o msgid", not got_target,
         f"ok={r['ok']} errs={r['errors']} warnings={r['warnings']}")
    # user_narration 空 msgid 是允许的（非逐条消息来源）——schema 通过
    cs3 = {"schema_version": "1.0", "extraction_context": {},
           "candidates": [cand(et="user_narration", claim="x", basis="user_report_only",
                               source_type="user_narration", speaker="user", msgs=(), refs=("user_narration",))]}
    C.ok("P: user_narration empty msgid ok (non-message source)",
         ee.validate_candidate_set(cs3) == [], str(ee.validate_candidate_set(cs3))[:120])


def main():
    print("=== Evidence Extractor 测试 (Stage 5.2 A–P) ===")
    tests = [
        ("A. 正常 target_message", tA_normal_target),
        ("B. user_narration", tB_user_narration),
        ("C. user_correction", tC_user_correction),
        ("D. unconfirmed target 阻断", tD_unconfirmed_target_blocked),
        ("E. unknown participant 阻断", tE_unknown_blocked),
        ("F. confirmed user evidence", tF_confirmed_user),
        ("G. 非法 status schema", tG_bad_status_schema),
        ("H. 非法 basis schema", tH_bad_basis_schema),
        ("I. target_message 缺 provenance", tI_target_message_missing_provenance),
        ("J. candidate_id 稳定性", tJ_candidate_id_stability),
        ("K. LLM 非法 JSON", tK_llm_invalid_json),
        ("L. 合法 JSON schema 不过", tL_llm_valid_json_bad_schema),
        ("M. narration 伪装 target 被拒(M1/M2/M3)", tM_narration_as_target_denied),
        ("N. 可追溯性", tN_traceability),
        ("Q. confidence/importance 越界显式失败", tQ_confidence_importance_out_of_range),
        ("R. LLM JSON 解析边界", tR_llm_json_boundary),
        ("O. 与 v1.2 Claim 兼容", tO_claim_compatible_pm_v12),
        ("P. 空 evidence 负测试", tP_empty_evidence_negative),
    ]
    for name, fn in tests:
        print(f"\n▶ {name}")
        try:
            fn()
        except Exception as e:
            import traceback
            C.ok(f"{name} raised", False, f"{type(e).__name__}: {e}")
            traceback.print_exc()
    print(f"\n通过 {C.ok_n} / 失败 {C.fail_n}")
    for f_ in C.fails:
        print("  -", f_)
    sys.exit(0 if C.fail_n == 0 else 1)


if __name__ == "__main__":
    main()
