#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Evidence Extractor：Confirmed Evidence → Evidence Candidates

职责（只做一件事）：把【已经确认】的输入材料，提取为可审计的 Evidence Candidate。
不做 Candidate Merge / Persona Builder / Memory Builder / Correction Overlay / Runtime。

数据流：
  confirmed target 消息 (message v1.2 ChatImport 经 import_pipeline 身份闸门)
  + 用户口述 user_narration（标记 source_type=user_narration）
  + 用户纠正 user_correction（来自 persona_memory v1.2 corrections，basis=correction）
      → LLM 语义提取（injectable，可 mock）
      → evidence candidates（过 evidence_candidate.schema v1.0 校验）
      → 返回

安全边界（由代码强制，不靠 prompt）：
  1. target_message candidate 只能来自 participant.confirmed==target 的消息；
     未确认 target / unknown / other 消息绝不产生 target_message candidate。
  2. user_narration 必须 basis=user_report_only 或 source_type 标记；禁止被写成 target-derived。
  3. user_correction 使用 basis=correction，保留对应 correction provenance。
  4. speaker_role / evidence_type / status / claim.basis 由本层强校验，非法值 schema 直接失败。
  5. LLM 失败不伪造 candidate；schema 校验失败显式失败，不允许 silent repair。
  6. candidate_id 确定性派生（canonical），不含 run 级信息。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import unicodedata
from datetime import datetime
from typing import Callable, Dict, List, Optional

try:
    from import_pipeline import (
        messages_belonging_to_confirmed_target, target_identity_snapshot,
        confirmed_target_keys,
    )
except Exception as _e:  # pragma: no cover - 仅用于直接运行本文件时
    messages_belonging_to_confirmed_target = None
    target_identity_snapshot = None
    confirmed_target_keys = None

SCHEMA_VERSION = "1.0"
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "evidence_candidate.schema.json")

# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------
class ExtractorError(Exception):
    """Extractor 层错误（可诊断）。"""


class SchemaValidationError(ExtractorError):
    """输出候选未通过 evidence_candidate schema。"""


class LLError(ExtractorError):
    """LLM 返回不可用结果。"""


class _NormalizeReject(ExtractorError):
    """单个候选结构性非法 → 拒绝并让整批显式失败（不静默修复）。"""


# ---------------------------------------------------------------------------
# 校验器
# ---------------------------------------------------------------------------
_VALIDATOR = None
_FORMAT = None


def _load_validator():
    global _VALIDATOR, _FORMAT
    if _VALIDATOR is not None:
        return _VALIDATOR
    try:
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
        with open(SCHEMA_PATH, encoding="utf-8") as f:
            schema = json.load(f)
        _VALIDATOR = Draft202012Validator(schema, format_checker=FormatChecker())
    except ImportError:
        raise ExtractorError("jsonschema 库不可用，无法校验 candidate 输出")
    return _VALIDATOR


def validate_candidate_set(data: dict) -> List[str]:
    v = _load_validator()
    return [f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in v.iter_errors(data)]


# ---------------------------------------------------------------------------
# canonical 化 / 确定性 id
# ---------------------------------------------------------------------------
def canonicalize_claim(value: str) -> str:
    """canonical_claim：NFKC → 去空白 → 去标点 → 小写 → 折叠句尾单字语气词。"""
    s = unicodedata.normalize("NFKC", value or "")
    s = re.sub(r"\s+", "", s)
    # 保留字母数字与中日韩，其余（标点/符号）去除
    s = "".join(ch for ch in s if ch.isalnum() or "一" <= ch <= "鿿"
                or "぀" <= ch <= "ヿ" or "가" <= ch <= "힯")
    s = s.lower()
    # 折叠句尾单字语气词（啊/呀/哦/呢/哈/吧/吗），仅限结尾一个
    for p in ("啊", "呀", "哦", "呢", "哈", "吧", "吗"):
        if s.endswith(p):
            s = s[:-1]
            break
    return s or "_empty_"


def compute_candidate_id(evidence_type: str, speaker_role: str, claim_value: str) -> str:
    """确定性候选 ID。

    canonical = evidence_type \x1f speaker_role \x1f canonical_claim
    不含：supporting_message_ids/source_ref/sequence/created_at/extraction run/输出顺序。
    """
    canon = "\x1f".join([evidence_type, speaker_role, canonicalize_claim(claim_value)])
    digest = hashlib.sha1(canon.encode("utf-8", "surrogatepass")).hexdigest()
    return "c_" + digest[:16]


# ---------------------------------------------------------------------------
# 输入门：确认 target 消息
# ---------------------------------------------------------------------------
def confirmed_target_messages_from_import(chat_import: dict) -> List[dict]:
    """只返回 confirmed target 的消息。上游 identity 闸门：confirmed=false/unknown 一律挡。"""
    if messages_belonging_to_confirmed_target is None:
        raise ExtractorError("import_pipeline 不可导入，无法执行身份闸门")
    return list(messages_belonging_to_confirmed_target(chat_import))


def is_confirmed_target_participant(chat_import: dict) -> bool:
    snap = target_identity_snapshot(chat_import)
    return snap["confirmed_target"] is not None


# ---------------------------------------------------------------------------
# 输入材料组装
# ---------------------------------------------------------------------------
def _build_target_input(chat_import: dict) -> List[dict]:
    """把 confirmed target 消息转成 extractor 的内部输入行（不丢 provenance/speaker/时间）。"""
    rows = []
    for m in confirmed_target_messages_from_import(chat_import):
        s = m.get("sender") or {}
        rows.append({
            "kind": "target_message",
            "message_id": m.get("id"),
            "source_ref": chat_import.get("source_ref"),
            "text": m.get("body") or "",
            "sender_role": "target",
            "speaker_name": s.get("name"),
            "sent_at": m.get("sent_at") or m.get("sent_at_raw"),
            "conversation": chat_import.get("conversation_title"),
        })
    return rows


def build_narration_input(text: str, source_ref: str) -> dict:
    """用户口述作为一行 user_narration 输入。"""
    return {"kind": "user_narration", "text": text, "source_ref": source_ref}


def build_correction_input(corr: dict) -> dict:
    """用户纠正作为一行 user_correction 输入（来自 persona_memory v1.2 corrections）。"""
    return {"kind": "user_correction", "text": f"{corr.get('user_statement','')} → {corr.get('corrected_value','')}",
            "source_ref": "correction", "correction_id": corr.get("id")}


# ---------------------------------------------------------------------------
# LLM 抽象（injectable）
# ---------------------------------------------------------------------------
def default_llm(prompt: str, *, llm=None):
    """默认不可用——必须注入。"""
    raise LLError("未注入 LLM。证据提取必须显式提供可调用的 llm(prompt) -> str。")


def mock_llm_factory(responses: List[str], *, inject_meta=True):
    """测试用 mock：按调用序号返回预设 JSON 字符串。"""
    it = iter(responses)

    def _llm(prompt: str) -> str:
        return next(it)

    return _llm


# ---------------------------------------------------------------------------
# 主流程：证据提取
# ---------------------------------------------------------------------------
def extract_evidence(*, target_rows: Optional[List[dict]] = None,
                     narration_text: Optional[str] = None,
                     narration_source_ref: Optional[str] = None,
                     corrections: Optional[List[dict]] = None,
                     chat_import: Optional[dict] = None,
                     llm: Optional[Callable[[str], str]] = None,
                     extraction_context: Optional[dict] = None) -> dict:
    """Evidence → Candidates。

    输入二选一提供 target 材料：
      - chat_import: dict —— 内部自动执行 confirmed target 闸门，取 confirmed target 消息；
        若该 import 无 confirmed target → target 输入为空（不产出任何 target_message）。
      - target_rows: list —— 已由调用方过闸门的行（测试注入用）。
    narration_text / corrections 为可选的 user 侧输入。
    llm: 可调用，prompt -> 原始文本。未注入则抛错。
    返回 {ok, candidate_set, errors, warnings}；失败时 ok=False。
    """
    errors: List[str] = []
    warnings: List[str] = []

    if llm is None:
        return {"ok": False, "candidate_set": None, "errors": ["未注入 LLM"],
                "warnings": []}

    # ---- 组装输入行（安全边界：代码门，非 prompt）----
    rows: List[dict] = []
    if chat_import is not None:
        rows += _build_target_input(chat_import)
        if not is_confirmed_target_participant(chat_import):
            warnings.append("该 import 无 confirmed target：不产出任何 target_message candidate")
    if target_rows is not None:
        rows += list(target_rows)
    if narration_text is not None and narration_text.strip():
        rows.append(build_narration_input(narration_text, narration_source_ref or "user_narration"))
    if corrections:
        for c in corrections:
            rows.append(build_correction_input(c))

    if not rows:
        return {"ok": True, "candidate_set": {"schema_version": SCHEMA_VERSION,
                                              "extraction_context": extraction_context or {},
                                              "candidates": []},
                "errors": [], "warnings": warnings}

    # ---- 构造 prompt（只负责语义提取，不负责安全边界）----
    prompt_rows = []
    for i, r in enumerate(rows):
        prompt_rows.append(
            f"<row i={i} kind={r['kind']} src={r.get('source_ref') or ''} "
            f"msgid={r.get('message_id') or ''} sent={r.get('sent_at') or ''}>\n"
            f"{r.get('text') or ''}\n</row>"
        )
    prompt = (
        "你是证据提取器。从下列【已确认】输入行中，提取可作为 Persona/Memory 依据的"
        "证据候选（Evidence Candidate）。\n"
        "约束：\n"
        "  - 只能输出 JSON 数组，每元素一个候选，字段："
        "evidence_type ∈ {target_message,user_narration,user_correction,photo_exif,social_post}, "
        "claim.value(命题句,直接可复述), claim.basis ∈ {direct_quote,multi_evidence,single_weak,"
        "user_report_only,inferred,correction}, "
        "supporting_message_ids(本候选所依据的消息行 i 对应的 msgid), "
        "source_refs, speaker_role ∈ {user,target,other,unknown}, "
        "observed_at(ISO或null), confidence(0-1 支持度), importance(1-5), "
        "source_type ∈ {wechat_log,qq_log,social,photo,user_narration,user_input,correction,unknown}.\n"
        "  - kind=user_narration 的行：evidence_type=user_narration 时 speaker_role 必须=user 且 "
        "claim.basis 必须=user_report_only（程序不变量，LLM 无权改为 target/direct_quote）。\n"
        "  - kind=user_correction 的行用 basis=correction。\n"
        "  - 不要补全没有证据的细节。宁可少提取，不可编造。\n"
        "  - 只输出 JSON，不要任何其它文字。\n\n"
        + "\n".join(prompt_rows)
    )

    try:
        raw = llm(prompt)
    except Exception as e:
        return {"ok": False, "candidate_set": None,
                "errors": [f"LLM 调用失败: {e}"], "warnings": warnings}

    # ---- 解析 LLM 输出（不静默修复）----
    data = _parse_llm_json(raw)
    if data is None:
        return {"ok": False, "candidate_set": None,
                "errors": ["LLM 返回了无法解析的 JSON（显式失败，不伪造 candidate）"],
                "warnings": warnings}
    if not isinstance(data, list):
        return {"ok": False, "candidate_set": None,
                "errors": ["LLM 输出应为 JSON 数组，实际是 " + type(data).__name__],
                "warnings": warnings}

    # ---- 逐条规范化成 candidate（代码强制安全边界；任何结构性非法 → 显式失败整批）----
    candidates: List[dict] = []
    row_index = {i: r for i, r in enumerate(rows)}
    for idx, item in enumerate(data):
        if not isinstance(item, dict):
            errors.append(f"候选 #{idx}: 不是对象，LLM 输出结构性非法 → 显式失败")
            return {"ok": False, "candidate_set": None, "errors": errors, "warnings": warnings}
        try:
            c = _normalize_candidate(item, rows, row_index, warnings)
        except _NormalizeReject as e:
            errors.append(f"候选 #{idx}: {e} → 显式失败（不静默修复）")
            return {"ok": False, "candidate_set": None, "errors": errors, "warnings": warnings}
        if c is None:
            errors.append(f"候选 #{idx}: 无法规范化 → 显式失败")
            return {"ok": False, "candidate_set": None, "errors": errors, "warnings": warnings}
        candidates.append(c)

    # ---- schema 校验：任何不合法 → 显式失败 ----
    candidate_set = {"schema_version": SCHEMA_VERSION,
                     "extraction_context": extraction_context or {},
                     "candidates": candidates}
    verrs = validate_candidate_set(candidate_set)
    if verrs:
        return {"ok": False, "candidate_set": None,
                "errors": ["schema 校验失败（显式失败，不 silent repair）: " + verrs[0]
                           + (f" (+{len(verrs)-1} 更多)" if len(verrs) > 1 else "")],
                "warnings": warnings}
    return {"ok": True, "candidate_set": candidate_set, "errors": errors, "warnings": warnings}


def _parse_llm_json(raw: str):
    """宽容取第一个 [...] 数组；否则严格解析。失败返回 None。"""
    if raw is None:
        return None
    s = raw.strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\[[\s\S]*\]", s)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None


def _normalize_candidate(item: dict, rows: List[dict], row_index: Dict[int, dict],
                         warnings: List[str]) -> Optional[dict]:
    """把一个 LLM 候选规范化；含代码层安全边界修正/拒绝。"""
    et = item.get("evidence_type")
    claim = item.get("claim") or {}
    basis = claim.get("basis")
    speaker = item.get("speaker_role")
    src_refs = item.get("source_refs") or []
    msg_ids = item.get("supporting_message_ids") or []
    source_type = item.get("source_type")

    if et not in ("target_message", "user_narration", "user_correction",
                  "photo_exif", "social_post"):
        raise _NormalizeReject(f"非法 evidence_type: {et!r}")

    # ---- 代码层安全边界（结构性非法 → raise，整批显式失败）----
    if et == "target_message":
        # speaker 必须 target（身份闸门）
        if speaker != "target":
            raise _NormalizeReject("target_message 的 speaker_role 非 target（身份闸门）")
        if not msg_ids:
            raise _NormalizeReject("target_message 缺 supporting_message_ids（无法追溯消息）")
        if not src_refs:
            raise _NormalizeReject("target_message 缺 source_refs（provenance 缺失）")
    # user_narration 程序级不变量（LLM 无权覆盖）：
    #   evidence_type==user_narration → speaker_role 必须为 user；claim.basis 必须强制为 user_report_only。
    # LLM 若给其它 speaker/basis：一律规范化到 user + user_report_only（并记 warning），绝不静默接受伪装。
    if et == "user_narration":
        if speaker != "user":
            warnings.append(f"user_narration 的 speaker_role 被写成 {speaker!r}，代码层强制为 user（不变量）")
            speaker = "user"
        if basis != "user_report_only":
            warnings.append(f"user_narration 的 basis 被写成 {basis!r}，代码层强制为 user_report_only（不变量）")
            basis = "user_report_only"
        if source_type not in ("user_narration", "user_input"):
            source_type = "user_narration"
    # user_correction 强制 basis=correction
    if et == "user_correction":
        basis = "correction"
        if source_type not in ("correction",):
            source_type = "correction"

    # speaker 词表过滤
    if speaker not in ("user", "target", "other", "unknown"):
        raise _NormalizeReject(f"非法 speaker_role: {speaker!r}")
    # evidence_type 与 speaker 的合理性（代码门）
    if et == "target_message" and speaker == "target" and source_type in ("user_narration", "user_input"):
        warnings.append("target_message 的 source_type 不能是 user_narration/user_input，纠正")
        source_type = "wechat_log"

    # 时间
    observed_at = item.get("observed_at")
    if observed_at and not _is_iso(observed_at):
        observed_at = None
    tp = item.get("time_period")
    if tp is not None and not isinstance(tp, dict):
        tp = None

    # confidence / importance：越界/非数值 → 显式失败（不静默 clamp，不自动修复）
    conf = item.get("confidence")
    if conf is None:
        raise _NormalizeReject("confidence 缺失")
    if not isinstance(conf, (int, float)) or isinstance(conf, bool):
        raise _NormalizeReject(f"confidence 非数值: {conf!r}")
    conf = float(conf)
    if conf < 0.0 or conf > 1.0:
        raise _NormalizeReject(f"confidence 越界: {conf}（须在 0..1）")
    imp = item.get("importance")
    if imp is None:
        raise _NormalizeReject("importance 缺失")
    if not isinstance(imp, (int, float)) or isinstance(imp, bool):
        raise _NormalizeReject(f"importance 非数值: {imp!r}")
    if imp != int(imp) or imp < 1 or imp > 5:
        raise _NormalizeReject(f"importance 越界/非整数: {imp}（须为 1..5 整数）")
    imp = int(imp)

    if not claim.get("value") or not isinstance(claim.get("value"), str):
        raise _NormalizeReject("claim.value 缺失")

    cid = compute_candidate_id(et, speaker, claim["value"])
    return {
        "candidate_id": cid,
        "evidence_type": et,
        "claim": {"value": claim["value"], "basis": basis},
        "supporting_message_ids": [str(x) for x in msg_ids],
        "source_refs": [str(x) for x in src_refs],
        "speaker_role": speaker,
        "observed_at": observed_at,
        "time_period": tp,
        "confidence": conf,
        "importance": imp,
        "source_type": source_type,
        "status": item.get("status", "pending"),
        "conflicts_with": item.get("conflicts_with") or [],
        "created_at": item.get("created_at"),
        "updated_at": None,
    }


def _is_iso(v: str) -> bool:
    try:
        datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# CLI（诊断用）
# ---------------------------------------------------------------------------
def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Evidence Extractor（诊断）")
    ap.add_argument("--chat-import", default=None, help="ChatImport JSON 路径")
    ap.add_argument("--narration", default=None)
    ap.add_argument("--narration-source-ref", default=None)
    ap.add_argument("--output", default=None)
    args = ap.parse_args(argv)
    print("Evidence Extractor 是库模块：请从代码调用 extract_evidence() 并注入 llm。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
