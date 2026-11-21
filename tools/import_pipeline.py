#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Import Pipeline：把 Raw Source 可靠地变成 已验证的 Evidence 层

数据流：
  Raw Source → Parser(parse_file_to_import)
             → ChatImport
             → Schema Validation (message.schema v1.2)
             → Participant Resolution / Target Confirmation 闸门
             → Cross-import Candidate Deduplication
             → Import Report

本层只负责：保留证据、验证结构、解决来源、标记身份状态、发现重复候选。
**不负责**判断"这个人是谁"——那是 Persona/Memory 层基于 verified Evidence 做的高层语义抽取。

核心纪律：
  1. confirmed=true 是唯一可作为 Persona/Memory target 身份依据的角色状态。
     confirmed=false 的 target 只是候选，下游 target 数据流一律不消费。
  2. 每个 parser 输出必须过 schema 校验；失败则 import 不得标记成功，产生可诊断错误，
     且绝不静默篡改原始数据。
  3. 去重只看"候选"：
       content_fingerprint 相同  → 只是 candidate，不能直接判为同一条
       content_fingerprint 不同  → 也不能直接证明不是同一条
     结论分四档：exact / probable / unresolved / distinct。
  4. 去重永不删除原始来源：同一逻辑消息可能存在于多个 source_ref，provenance 保留其来源关系。
  5. 报告与日志不得输出聊天正文。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from chat_parser_common import ParserError, log, basename_only
import wechat_parser
import qq_parser

SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "message.schema.json")

# 时间窗口：sent_at 在容差内视为"可能同一时刻"（去重候选用，非判定）
TIME_TOLERANCE_SECONDS = 90.0
# 相邻消息上下文窗口：比较时纳入前后各 N 条
CTX_WINDOW = 2

# ---------------------------------------------------------------------------
# 解析文件（分发到对应 parser 的库接口）
# ---------------------------------------------------------------------------
def _detect_parser(path: str) -> str:
    lower = path.lower()
    if lower.endswith((".mht", ".mhtml")):
        return "unsupported_qq_mht"
    if lower.endswith(".txt"):
        return "qq"  # 由内容判定：含消息对象头走 qq；否则 wechat 会自判
    if lower.endswith(".json"):
        return "wechat"
    if lower.endswith((".csv", ".db", ".sqlite", ".sqlite3", ".html", ".htm")):
        return "unsupported"
    # 无扩展名：让 wechat 探测（它会按内容拒绝）
    return "wechat"


def parse_source_file(path: str, *, target: str = "", self_names: str = "",
                      self_account: str = "", source_ref: Optional[str] = None) -> dict:
    """解析单个源文件 → {ok, error, batch_warnings, imports:[{chat_import, warnings}]}。"""
    kind = _detect_parser(path)
    if kind == "unsupported":
        return {"ok": False, "error": "不支持的扩展名（csv/db/sqlite/html 本版无真实解析器）",
                "imports": [], "batch_warnings": []}
    if kind == "unsupported_qq_mht":
        return {"ok": False, "error": "QQ mht 本版不支持：请用 QQ txt 导出", "imports": [], "batch_warnings": []}
    if kind == "qq":
        # 快速判读：无 '消息对象' 头的 txt 交给 wechat
        try:
            head = open(path, encoding="utf-8", errors="ignore").read(4000)
        except OSError as e:
            return {"ok": False, "error": f"读取失败: {e}", "imports": [], "batch_warnings": []}
        if "消息对象" in head or "消息分组" in head:
            return qq_parser.parse_file_to_import(
                file=path, target=target, self_account=self_account,
                self_names=self_names, source_ref=source_ref)
        return wechat_parser.parse_file_to_import(
            file=path, target=target, self_names=self_names, source_ref=source_ref)
    return wechat_parser.parse_file_to_import(
        file=path, target=target, self_names=self_names, source_ref=source_ref)


# ---------------------------------------------------------------------------
# Schema validation（可诊断、不静默修复）
# ---------------------------------------------------------------------------
class ValidationResult:
    def __init__(self):
        self.ok = True
        self.errors: List[str] = []


def _load_validator():
    global _VALIDATOR
    if _VALIDATOR is not None:
        return _VALIDATOR
    try:
        import jsonschema
        from jsonschema import Draft202012Validator, FormatChecker
        from datetime import datetime as _dt

        def _iso(v):
            if not isinstance(v, str):
                return True
            try:
                _dt.fromisoformat(v.replace("Z", "+00:00"))
                return True
            except ValueError:
                return False

        FormatChecker.checkers["date-time"] = (lambda i: _iso(i), ValueError)
        with open(SCHEMA_PATH, encoding="utf-8") as f:
            schema = json.load(f)
        _VALIDATOR = Draft202012Validator(schema, format_checker=FormatChecker())
    except ImportError:
        _VALIDATOR = None
    return _VALIDATOR


_VALIDATOR = None


def validate_chat_import(data: dict) -> ValidationResult:
    """严格校验 ChatImport。失败 → errors 可诊断；成功才允许进入下游。"""
    out = ValidationResult()
    v = _load_validator()
    if v is None:
        out.ok = False
        out.errors.append("jsonschema 库不可用，无法校验；为安全起见标记失败")
        return out
    errors = sorted(v.iter_errors(data), key=lambda e: list(e.path))
    if errors:
        out.ok = False
        for e in errors:
            loc = "/".join(map(str, e.path)) or "<root>"
            out.errors.append(f"{loc}: {e.message}")
    return out


# ---------------------------------------------------------------------------
# Target confirmation 闸门（代码层强制）
# ---------------------------------------------------------------------------
def target_identity_snapshot(chat_import: dict) -> dict:
    """从 participants 生成 target 身份快照（含确认状态），供下游 target 数据流消费。

    返回 {confirmed_target: dict|None, candidates:[...], raw_participants:[...]}
    - 仅 confirmed=true 的 target 进入 confirmed_target。
    - confirmed=false 的 target 只是 candidates，绝不会出现在 confirmed_target。
    """
    participants = chat_import.get("participants", [])
    targets = [p for p in participants if p.get("role") == "target"]
    confirmed = [p for p in targets if p.get("confirmed") is True]
    candidates = [p for p in targets if p.get("confirmed") is not True]
    return {
        "confirmed_target": confirmed[0] if confirmed else None,
        "candidates": candidates,
        "raw_participants": participants,
    }


def confirmed_target_keys(chat_import: dict) -> set:
    """当前 import 中 confirmed target 的可匹配键集合（account_id + 各名字归一化）。

    返回空集表示：没有 confirmed target —— 下游 target 数据流必须为空。
    """
    snap = target_identity_snapshot(chat_import)
    if not snap["confirmed_target"]:
        return set()
    p = snap["confirmed_target"]
    keys = set()
    if p.get("account_id"):
        keys.add(str(p["account_id"]))
    for n in p.get("names", []):
        keys.add(re.sub(r"\s+", "", n))
    return keys


def messages_belonging_to_confirmed_target(chat_import: dict) -> List[dict]:
    """返回该 import 中确定归属已确认 target 的消息。

    规则（代码层强制）：
      - 没有 confirmed target（confirmed=false 或 unknown）→ 返回 []，一条都不给下游。
      - 有 confirmed target → 仅当其 sender_key / sender.name 命中确认映射时才归属，
        unknown/other/未命中的一律排除。
    """
    keys = confirmed_target_keys(chat_import)
    if not keys:
        return []
    out = []
    for m in chat_import.get("messages", []):
        s = m.get("sender") or {}
        if s.get("role") != "target":
            continue
        sk = re.sub(r"\s+", "", s.get("sender_key") or "")
        nm = re.sub(r"\s+", "", s.get("name") or "")
        if sk in keys or nm in keys:
            out.append(m)
    return out


# ---------------------------------------------------------------------------
# Cross-import candidate deduplication
# ---------------------------------------------------------------------------
def _norm_ts(ts) -> Optional[float]:
    """把 sent_at(ISO 或 None) 解析成 epoch 秒；解析不了返回 None。"""
    if not ts:
        return None
    s = str(ts)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        return None


def _fmt_ts(value: Optional[float]) -> Optional[str]:
    if value is None:
        return None
    return datetime.fromtimestamp(value).isoformat()


def _strip(text: Optional[str]) -> str:
    return re.sub(r"\s+", "", text or "")


def _body_fp(m) -> str:
    """纯正文指纹（不含时间/发送者），用于时间戳归一不同的跨文件候选。"""
    body = _strip(m.get("body"))
    sk = (m.get("sender") or {}).get("sender_key") or ""
    canon = f"{sk}\x1f{body}"
    return "b_" + hashlib.sha1(canon.encode("utf-8", "surrogatepass")).hexdigest()[:16]


def _ctx(msgs: List[dict], idx: int) -> List[str]:
    """该消息在批内的相邻上下文指纹（前后各 CTX_WINDOW 条）。"""
    out = []
    for j in range(max(0, idx - CTX_WINDOW), min(len(msgs), idx + CTX_WINDOW + 1)):
        if j == idx:
            continue
        out.append(msgs[j].get("content_fingerprint") or "")
    return out


def dedupe_imports(imports: List[dict], *, source_refs: Optional[List[str]] = None) -> dict:
    """跨 source_ref 候选去重。

    imports: [{chat_import, warnings}]（已各自通过 schema 校验）

    结论分档（不对同指纹做最终判定，只分级）：
      exact     —— fingerprint + sender_key + sent_at(±容差) 全一致
      probable  —— fingerprint 一致但 sent_at/sender_key 有歧义；或时间戳归一不同但
                   相邻上下文(重叠前窗) + sender + 唯一指纹 强烈一致
      unresolved—— 有相同 fingerprint 候选，但上下文不足以定档
      distinct  —— 无任何候选关联

    返回 dict：
      records        list[{ id, key(uid), fingerprint, sent_at, sender_key, source_ref,
                            neighbours:[(rid,ref)], dedup, confidence }]
      clusters       list[list[uid]]  (exact 与 probable 的并查集连通组)
      stats          dict(exact/probable/unresolved/distinct 计数)
      note           str
    不删除任何记录；来源归属保留在各 source_ref。
    """
    # 展平：每条消息一个 record，携带 source_ref / 批内 index
    records: List[dict] = []
    for imp_idx, entry in enumerate(imports):
        ci = entry["chat_import"]
        sref = source_refs[imp_idx] if source_refs and imp_idx < len(source_refs) else ci.get("source_ref", f"src{imp_idx}")
        msgs = ci.get("messages", [])
        for idx, m in enumerate(msgs):
            sk = (m.get("sender") or {}).get("sender_key") or ""
            t = _norm_ts(m.get("sent_at"))
            records.append({
                "uid": len(records),
                "id": m.get("id"),
                "fingerprint": m.get("content_fingerprint"),
                "body_fp": _body_fp(m),
                "sender_key": sk,
                "sent_at": t,
                "sent_at_raw": m.get("sent_at_raw"),
                "source_ref": sref,
                "seq": m.get("sequence", idx),
                "ctx": _ctx(msgs, idx),
                "_imp_idx": imp_idx,
            })

    # 候选组索引：
    #   1) 完整 content_fingerprint 相同 → 强候选
    #   2) 纯正文+发送者相同（时间戳归一不同但正文一致）→ 候选
    by_fp: Dict[str, List[int]] = {}
    by_body: Dict[str, List[int]] = {}
    for r in records:
        by_fp.setdefault(r["fingerprint"] or "__none__", []).append(r["uid"])
        by_body.setdefault(r["body_fp"], []).append(r["uid"])

    dedup_tags = {r["uid"]: "distinct" for r in records}
    neighbours: Dict[int, List[tuple]] = {r["uid"]: [] for r in records}
    clusters: List[List[int]] = []
    cluster_member: Dict[int, int] = {}

    def union(g: List[int]):
        nonlocal clusters
        g = sorted(set(g))
        if len(g) < 2:
            return
        # 并入既有连通组
        existing = [i for i in g if i in cluster_member]
        if existing:
            cid = cluster_member[existing[0]]
            for u in g:
                if u in cluster_member and cluster_member[u] != cid:
                    old = cluster_member[u]
                    clusters[cid] += clusters[old]
                    clusters[old] = []
                    for uu in clusters[cid]:
                        cluster_member[uu] = cid
                elif u not in cluster_member:
                    clusters[cid].append(u)
                    cluster_member[u] = cid
            return
        clusters.append(g)
        for u in g:
            cluster_member[u] = len(clusters) - 1

    def classify(a: dict, b: dict) -> str:
        """判定两候选条目的关系档位。任何结论都不是最终"删一条"，只是分级候选。

        完整 content_fingerprint 已内含 sender_key + sent_at_raw + body + content_type，
        因此跨文件 fp 相同即意味着三者一致 → 强重复信号；但若任一方在同批内有
        同 fp 的兄弟消息（同秒同内容多条真消息），则"具体和哪条重复"有歧义 → unresolved。
        """
        same_sender = bool(a["sender_key"] and a["sender_key"] == b["sender_key"])
        full_fp_ok = bool(a["fingerprint"] and a["fingerprint"] == b["fingerprint"])
        body_fp_ok = a["body_fp"] == b["body_fp"]
        # 时间三态
        ta, tb = a["sent_at"], b["sent_at"]
        if ta is not None and tb is not None:
            dt_ok = abs(ta - tb) <= TIME_TOLERANCE_SECONDS
        elif ta is None and tb is None:
            dt_ok = bool(a["sent_at_raw"]) and a["sent_at_raw"] == b["sent_at_raw"]
        else:
            dt_ok = False
        ctx_overlap = bool(set(a["ctx"]) & set(b["ctx"]))
        # 歧义检测：任一方在其批内有同 fp 兄弟（真消息），则跨批匹配不唯一
        a_sib = a.get("_same_fp_sibling", False)
        b_sib = b.get("_same_fp_sibling", False)

        if full_fp_ok:
            if same_sender and dt_ok and not (a_sib or b_sib):
                return "exact"
            # 有歧义或时间/发送者证据不足 → 只给候选，不定档
            if same_sender:
                return "unresolved" if (a_sib or b_sib) else "probable"
            return "unresolved"
        # 完整指纹不同但纯正文+发送者一致（时间戳归一差异）且时间对得上 → probable
        if body_fp_ok and same_sender and dt_ok:
            return "probable"
        # 相邻上下文背书（同 sender + 正文一致 + 时间近但非容差内）→ probable
        if body_fp_ok and same_sender and ctx_overlap:
            return "probable"
        return "distinct"

    seen_pairs = set()
    rank = {"exact": 2, "probable": 1, "unresolved": 0, "distinct": -1}

    def record_pair(a: dict, b: dict, grade: str):
        pair = tuple(sorted((a["uid"], b["uid"])))
        if pair in seen_pairs:
            return
        seen_pairs.add(pair)
        neighbours[a["uid"]].append((b["uid"], b["source_ref"], grade))
        neighbours[b["uid"]].append((a["uid"], a["source_ref"], grade))
        if grade in ("exact", "probable"):
            # 取较强者
            for u in (a["uid"], b["uid"]):
                if rank[grade] > rank.get(dedup_tags.get(u, "distinct"), -1):
                    dedup_tags[u] = grade
            union([a["uid"], b["uid"]])

    # 预标记歧义：仅当【同一 import 内】存在同 fp 的兄弟消息（=同秒同内容的多条真消息）
    # 该消息跨批匹配才有歧义。跨 import 的同 fp 正是重复候选，不算兄弟。
    per_imp_fp: Dict[int, Dict[str, int]] = {}
    for r in records:
        bucket = per_imp_fp.setdefault(r["_imp_idx"], {})
        fp = r["fingerprint"] or "__none__"
        bucket[fp] = bucket.get(fp, 0) + 1
    for r in records:
        fp = r["fingerprint"] or "__none__"
        r["_same_fp_sibling"] = per_imp_fp[r["_imp_idx"]].get(fp, 0) >= 2

    def process_groups(groups):
        """遍历候选组，只处理跨批配对；同批内两条真消息绝不判重。"""
        for members in groups.values():
            if len(members) < 2:
                continue
            for i in range(len(members)):
                for j in range(i + 1, len(members)):
                    a, b = records[members[i]], records[members[j]]
                    if a["_imp_idx"] == b["_imp_idx"]:
                        continue   # 同批内同指纹 = 同秒同内容的多条真消息，保持独立
                    record_pair(a, b, classify(a, b))

    # 完整指纹候选组
    process_groups(by_fp)
    # 纯正文候选组（时间戳归一差异）
    process_groups(by_body)

    # 折叠空连通组
    clusters = [c for c in clusters if len(c) > 1]

    # 终态标签：有 unresolved 邻居 = 存在重复候选但无法确定和哪条对应 → 该记录应标 unresolved
    # （比"假装 distinct"更诚实，也绝不因歧义删除任何一条）
    for r in records:
        uid = r["uid"]
        if dedup_tags.get(uid) == "distinct" and neighbours[uid]:
            has_unres = any(n[2] == "unresolved" for n in neighbours[uid])
            has_exact = any(n[2] == "exact" for n in neighbours[uid])
            if has_exact:
                dedup_tags[uid] = "exact"
            elif has_unres:
                dedup_tags[uid] = "unresolved"
            else:
                dedup_tags[uid] = "probable"

    # 空壳回退：unresolved 却没有任何邻居 → 只是同批歧义，不跨批 → distinct
    for r in records:
        if dedup_tags[r["uid"]] == "unresolved" and not neighbours[r["uid"]]:
            dedup_tags[r["uid"]] = "distinct"

    stats = {"exact": 0, "probable": 0, "unresolved": 0, "distinct": 0}
    for r in records:
        stats[dedup_tags[r["uid"]]] = stats.get(dedup_tags[r["uid"]], 0) + 1

    out = []
    for r in records:
        uid = r["uid"]
        dedup = dedup_tags.get(uid, "distinct")
        out.append({
            "id": r["id"],
            "key": f"{r['source_ref']}::{r['seq']}::{r['id']}",
            "fingerprint": r["fingerprint"],
            "sent_at": _fmt_ts(r["sent_at"]),
            "sender_key": r["sender_key"],
            "source_ref": r["source_ref"],
            "neighbours": neighbours[uid],
            "dedup": dedup,
            "confidence": {"exact": 1.0, "probable": 0.6, "unresolved": 0.3, "distinct": 0.0}[dedup],
        })
    note = ("content_fingerprint 相同只构成候选，不代表同一条；"
            "exact=指纹+发送者+时间全一致；probable=强上下文候选；"
            "unresolved=有候选但不足以判定；distinct=无关联。"
            "任何档位都不删除原始来源，来源关系见 neighbours/source_ref。")
    return {"records": out, "clusters": clusters, "stats": stats, "note": note}


# ---------------------------------------------------------------------------
# Import Report
# ---------------------------------------------------------------------------
def build_report(*, source_file: str, parse_result: dict, validation_results: List[ValidationResult],
                 confirmed_snapshot: Optional[dict], dedup: Optional[dict],
                 warnings: List[str], errors: List[str]) -> dict:
    """生成批次 Import Report（不包含任何消息正文）。"""
    per_import = []
    total_parsed = 0
    total_failed = 0
    unknown_sender = 0
    for entry in parse_result.get("imports", []):
        ci = entry["chat_import"]
        msgs = ci.get("messages", [])
        n_unknown = sum(1 for m in msgs if (m.get("sender") or {}).get("role") == "unknown")
        unknown_sender += n_unknown
        total_parsed += len(msgs)
        total_failed += sum(1 for m in msgs if m.get("sequence") is None)
        per_import.append({
            "source_ref": ci.get("source_ref"),
            "platform": ci.get("platform"),
            "source_format": ci.get("source_format"),
            "total_messages": len(msgs),
            "unknown_sender_count": n_unknown,
            "participants": ci.get("participants", []),
        })

    confirmed_participants = 0
    unconfirmed_candidates = 0
    if confirmed_snapshot is not None:
        confirmed_participants = 1 if confirmed_snapshot.get("confirmed_target") else 0
        unconfirmed_candidates = len(confirmed_snapshot.get("candidates", []))

    status = "failed"
    if parse_result.get("ok") and all(v.ok for v in validation_results) and not errors:
        status = "success"

    report = {
        "source_file": basename_only(source_file),
        "source_ref": per_import[0]["source_ref"] if per_import else None,
        "platforms": sorted({p["platform"] for p in per_import}),
        "source_formats": sorted({str(p["source_format"]) for p in per_import}),
        "import_units": len(per_import),
        "total_messages": total_parsed,
        "successfully_parsed": total_parsed,
        "failed_messages": total_failed,
        "unknown_sender_count": unknown_sender,
        "confirmed_participants": confirmed_participants,
        "unconfirmed_candidates": unconfirmed_candidates,
        "schema_validation_ok": all(v.ok for v in validation_results) if validation_results else True,
        "per_import": per_import,
        "dedup": {
            "exact_duplicate_candidates": dedup["stats"]["exact"] if dedup else 0,
            "probable_duplicate_candidates": dedup["stats"]["probable"] if dedup else 0,
            "unresolved_candidates": dedup["stats"]["unresolved"] if dedup else 0,
            "distinct": dedup["stats"]["distinct"] if dedup else 0,
            "clusters": len(dedup["clusters"]) if dedup else 0,
        } if dedup else None,
        "warnings": warnings,
        "errors": errors,
        "final_status": status,
        "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return report


# ---------------------------------------------------------------------------
# 高层入口
# ---------------------------------------------------------------------------
def run_import_batch(files: List[str], *, target: str = "", self_names: str = "",
                     self_account: str = "", source_refs: Optional[List[str]] = None) -> dict:
    """处理一批源文件，返回 Import Report 汇总。每个文件独立解析/校验/报告。"""
    reports = []
    all_imports = []
    source_marks = []
    for fi, path in enumerate(files):
        sref = source_refs[fi] if source_refs and fi < len(source_refs) else None
        pr = parse_source_file(path, target=target, self_names=self_names,
                               self_account=self_account, source_ref=sref)
        vres = []
        errors = []
        warnings = list(pr.get("batch_warnings", []))
        if not pr.get("ok"):
            errors.append(pr.get("error") or "unknown parser failure")
        else:
            for entry in pr["imports"]:
                vr = validate_chat_import(entry["chat_import"])
                vres.append(vr)
                if not vr.ok:
                    errors.append(f"{entry['chat_import'].get('source_ref')}: schema 校验失败: "
                                  + "; ".join(vr.errors[:3]))
                warnings.extend(entry["warnings"])
            if not errors:
                all_imports.extend(pr["imports"])
                source_marks.extend(ci["chat_import"]["source_ref"] for ci in pr["imports"])

        # confirmed 快照（仅在该文件成功时才统计）
        confirmed_snap = None
        if pr.get("ok") and all(v.ok for v in vres):
            confirmed_snap = target_identity_snapshot(pr["imports"][0]["chat_import"])
        rep = build_report(source_file=path, parse_result=pr, validation_results=vres,
                           confirmed_snapshot=confirmed_snap, dedup=None,
                           warnings=warnings, errors=errors)
        reports.append(rep)
        for e in errors:
            log(f"[pipeline] 错误: {e}")

    # 跨文件 dedup（仅对通过校验的 import）
    dedup = None
    if all_imports:
        dedup = dedupe_imports(all_imports, source_refs=source_marks)

    # 汇总报告
    summary = {
        "files_processed": len(files),
        "files_succeeded": sum(1 for r in reports if r["final_status"] == "success"),
        "files_failed": sum(1 for r in reports if r["final_status"] == "failed"),
        "total_messages": sum(r["successfully_parsed"] for r in reports),
        "unknown_sender_count": sum(r["unknown_sender_count"] for r in reports),
        "confirmed_targets": sum(r["confirmed_participants"] for r in reports),
        "unconfirmed_target_candidates": sum(r["unconfirmed_candidates"] for r in reports),
        "dedup": dedup["stats"] if dedup else None,
        "dedup_clusters": len(dedup["clusters"]) if dedup else 0,
    }
    return {"reports": reports, "summary": summary, "dedup": dedup,
            "valid_imports": all_imports}


# ---------------------------------------------------------------------------
# CLI（诊断用，单文件 → 打印报告 JSON）
# ---------------------------------------------------------------------------
def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Import Pipeline：解析 + 校验 + 去重 + 报告")
    ap.add_argument("--files", required=True, help="源文件列表，逗号分隔")
    ap.add_argument("--target", default="")
    ap.add_argument("--self-names", default="")
    ap.add_argument("--self-account", default="")
    ap.add_argument("--source-ref", default=None, help="逗号分隔的稳定导入源 ID（与 --files 对齐）")
    ap.add_argument("--output", default=None, help="报告 JSON 输出路径（可选）")
    args = ap.parse_args(argv)

    files = [f.strip() for f in args.files.split(",") if f.strip()]
    refs = None
    if args.source_ref:
        refs = [r.strip() for r in args.source_ref.split(",") if r.strip()]
    result = run_import_batch(files, target=args.target, self_names=args.self_names,
                              self_account=args.self_account, source_refs=refs)
    for r in result["reports"]:
        log(json.dumps(r, ensure_ascii=False, indent=2))
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump({"reports": result["reports"], "summary": result["summary"]},
                      f, ensure_ascii=False, indent=2)
        log(f"[pipeline] 报告写入 {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
