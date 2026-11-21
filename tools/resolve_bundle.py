#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ResolvedEvidenceBundle（Stage 5.4）：CandidateSet + MergeResult → 只读 resolution/projection

输入：CandidateSet + MergeResult + optional corrections（调用方显式传入）
输出：ResolvedEvidenceBundle（过 resolved_evidence_bundle.schema v1.0）

5.4 是 deterministic resolution/projection layer：
  - 只读 join：不修改 CandidateSet / MergeResult
  - 不创建 Persona/Memory、不执行 correction overlay、不合成 claim、不删 candidate
  - 不用 LLM / embedding / semantic inference
  - representative.candidate_id 是唯一权威；snapshot 仅快照
  - candidate-level relation 是 source of truth；group-level 是 derived view
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

BUNDLE_SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                  "resolved_evidence_bundle.schema.json")
CAND_SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "evidence_candidate.schema.json")
MERGE_SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "merge_group.schema.json")

_GROUP_REL_TYPES = ("conflict", "temporal_evolution", "correction_relation", "supporting_related")


class ResolveError(Exception):
    """可诊断 resolution 错误。"""


def _load_validator(schema_path: str):
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
    with open(schema_path, encoding="utf-8") as f:
        schema = json.load(f)
    return Draft202012Validator(schema, format_checker=FormatChecker())


_cached = {}


def _validator(path: str):
    if path not in _cached:
        _cached[path] = _load_validator(path)
    return _cached[path]


def _schema_errs(validator, data) -> List[str]:
    return [f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in validator.iter_errors(data)]


# ---------------------------------------------------------------------------
# 输入契约校验
# ---------------------------------------------------------------------------
def _validate_input(candidate_set: dict, merge_result: dict) -> List[str]:
    errs = []
    errs += _schema_errs(_validator(CAND_SCHEMA_PATH), candidate_set)
    errs += _schema_errs(_validator(MERGE_SCHEMA_PATH), merge_result)
    return errs


# ---------------------------------------------------------------------------
# 解析入口
# ---------------------------------------------------------------------------
def resolve_bundle(*, candidate_set: dict, merge_result: dict,
                   corrections: Optional[List[dict]] = None) -> dict:
    """CandidateSet + MergeResult (+corrections) → ResolvedEvidenceBundle。

    返回 {ok, bundle, errors, warnings}。
    """
    errors: List[str] = []
    warnings: List[str] = []

    # 输入 schema 校验
    in_errs = _validate_input(candidate_set, merge_result)
    if in_errs:
        return {"ok": False, "bundle": None,
                "errors": ["输入 schema 校验失败: " + in_errs[0]
                           + (f" (+{len(in_errs)-1})" if len(in_errs) > 1 else "")],
                "warnings": warnings}

    cand_by_id = {c["candidate_id"]: c for c in candidate_set.get("candidates", [])}
    cand_ids = set(cand_by_id.keys())

    # ---- 6. candidate → group 映射 + 完整性校验（错误即 fail，不静默跳过）----
    candidate_to_group: Dict[str, str] = {}
    for g in merge_result.get("groups", []):
        gid = g["merge_group_id"]
        members = g.get("members", [])
        for m in members:
            cid = m["candidate_id"]
            if cid not in cand_ids:
                errors.append(f"group {gid} 成员 candidate {cid} 不存在于 CandidateSet")
                continue
            if cid in candidate_to_group:
                # active candidate 属于多个 group → fail
                errors.append(f"active candidate {cid} 出现在多个 group: "
                              f"{candidate_to_group[cid]} 与 {gid}")
                continue
            candidate_to_group[cid] = gid
        # representative candidate_id 必须存在
        rep = g.get("representative", {})
        rep_cid = rep.get("candidate_id")
        if rep_cid is None or rep_cid not in cand_ids:
            errors.append(f"group {gid} representative candidate {rep_cid} 不存在于 CandidateSet")
    if errors:
        return {"ok": False, "bundle": None,
                "errors": ["输入污染: " + "; ".join(errors[:10])], "warnings": warnings}

    # relation endpoint candidate 必须存在；merge_group endpoint 必须存在
    mg_ids = {g["merge_group_id"] for g in merge_result.get("groups", [])}
    for rel in merge_result.get("relations", []):
        for side in ("source_a", "source_b"):
            ep = rel.get(side, {})
            k, i = ep.get("kind"), ep.get("id")
            if k == "candidate":
                if i not in cand_ids:
                    errors.append(f"relation {rel.get('relation_id')} 端点 candidate {i} 不存在")
            elif k == "merge_group":
                if i not in mg_ids:
                    errors.append(f"relation {rel.get('relation_id')} 端点 group {i} 不存在")
    if errors:
        return {"ok": False, "bundle": None,
                "errors": ["输入污染: " + "; ".join(errors[:10])], "warnings": warnings}

    # ---- resolve group endpoints ----
    def endpoint_group(ep: dict) -> Tuple[str, bool]:
        """返回 (group_id, is_candidate_kind)。resolve 失败抛错（已在上方校验）。"""
        if ep["kind"] == "merge_group":
            return ep["id"], False
        return candidate_to_group[ep["id"]], True

    # ---- 7. resolved_relations（透传副本 + 已解析 group）----
    resolved_relations: List[dict] = []
    for rel in merge_result.get("relations", []):
        epa, epb = rel["source_a"], rel["source_b"]
        ga, ka = endpoint_group(epa)
        gb, kb = endpoint_group(epb)
        resolved_relations.append({
            "relation_id": rel["relation_id"],
            "relation_type": rel["relation_type"],
            "relation_confidence": rel.get("relation_confidence"),
            "direction": rel.get("direction"),
            "source_a": {"candidate_id": epa["id"], "group_id": ga},
            "source_b": {"candidate_id": epb["id"], "group_id": gb},
            "reason": rel.get("reason"),
            "basis_method": rel.get("basis_method"),
        })

    # ---- 8/9/10/11. group-level relations（去重 + confidence + self-edge 防御）----
    group_rel_map: Dict[Tuple[str, str, str], dict] = {}
    for rel in merge_result.get("relations", []):
        rt = rel["relation_type"]
        if rt not in _GROUP_REL_TYPES:
            continue  # same/supporting_same_core = 组内；unrelated/unresolved = 无组级边
        epa, epb = rel["source_a"], rel["source_b"]
        ga, ka = endpoint_group(epa)
        gb, kb = endpoint_group(epb)
        if ga == gb:
            warnings.append(f"relation {rel['relation_id']} 两端同组 {ga}（{rt}），保留 candidate 级，跳过 self-edge")
            continue
        key = (min(ga, gb), max(ga, gb), rt)
        entry = group_rel_map.get(key)
        if entry is None:
            direction = rel.get("direction")
            # direction 表达以 group_a/group_b 为准需归一：若 key 交换过顺序则翻转 direction
            ga_key, gb_key = key[0], key[1]
            if (ga, gb) != (ga_key, gb_key):
                direction = _flip_direction(direction)
            entry = {
                "group_a": ga_key,
                "group_b": gb_key,
                "relation_type": rt,
                "evidence": [],
                "direction_conflict": False,
                "relation_confidence": 0.0,
                "advisory": (rt == "supporting_related"),
            }
            group_rel_map[key] = entry
        entry["evidence"].append(rel["relation_id"])
        # confidence + direction-conflict
        rc = rel.get("relation_confidence") or 0.0
        entry["relation_confidence"] = max(entry["relation_confidence"], rc)
        cur_dir = entry.get("_dir")
        this_dir = rel.get("direction")
        ga_key, gb_key = key[0], key[1]
        if (ga, gb) != (ga_key, gb_key):
            this_dir = _flip_direction(this_dir)
        if cur_dir is None:
            entry["_dir"] = this_dir
        elif this_dir is not None and cur_dir != this_dir:
            entry["direction_conflict"] = True

    group_level_relations: List[dict] = []
    rel_by_id = {rel["relation_id"]: rel for rel in merge_result.get("relations", [])}
    for key, e in sorted(group_rel_map.items()):
        evidence = sorted(set(e["evidence"]))
        rel_conf = e["relation_confidence"]
        if e.get("direction_conflict"):
            # 取 source relation 的最小 confidence
            rel_conf = min(
                (rel_by_id[rid].get("relation_confidence") or 0.0)
                for rid in evidence if rid in rel_by_id
            )
        gl = {
            "group_a": e["group_a"],
            "group_b": e["group_b"],
            "relation_type": e["relation_type"],
            "direction": e.get("_dir"),
            "evidence": evidence,
            "relation_confidence": rel_conf,
            "advisory": e["advisory"] or e.get("direction_conflict", False),
            "time_info": None,
        }
        # temporal_evolution: time_info 取自 source relation 的真实候选端点（非 group rep）
        if e["relation_type"] == "temporal_evolution":
            a_times, b_times = [], []
            for rid in evidence:
                rel = rel_by_id[rid]
                ca = rel["source_a"]["id"]
                cb = rel["source_b"]["id"]
                # 依据归一化方向归到 a/b 组
                ra, rb = (ca, cb)
                # 依据关系里端点是否在 a 组来定
                ga_of = candidate_to_group.get(ra)
                gb_of = candidate_to_group.get(rb)
                if ga_of == e["group_a"] and gb_of == e["group_b"]:
                    a_cand, b_cand = cand_by_id.get(ra), cand_by_id.get(rb)
                else:
                    a_cand, b_cand = cand_by_id.get(rb), cand_by_id.get(ra)
                if a_cand:
                    a_times.append((a_cand.get("observed_at"), a_cand.get("time_period")))
                if b_cand:
                    b_times.append((b_cand.get("observed_at"), b_cand.get("time_period")))
            def _pick(ts):
                ts = [t for t in ts if t[0] is not None or t[1] is not None]
                return sorted(ts, key=lambda t: (t[0] is None, t[0] or ""))[0] if ts else (None, None)
            a_obs, a_tp = _pick(a_times)
            b_obs, b_tp = _pick(b_times)
            gl["time_info"] = {
                "a_observed_at": a_obs,
                "b_observed_at": b_obs,
                "a_time_period": a_tp,
                "b_time_period": b_tp,
            }
        group_level_relations.append(gl)

    # ---- 15. unresolved（单侧，不猜测 pair）----
    unresolved: List[dict] = []
    for cid in sorted(merge_result.get("unresolved_candidate_ids", [])):
        unresolved.append({
            "candidate_id": cid,
            "reason": "参与了 5.3 未决比较，pair 信息缺失，未建立任何关系",
        })

    # ---- 5/11/12. groups（representative 权威 + snapshot_stale）----
    groups: List[dict] = []
    for g in merge_result.get("groups", []):
        gid = g["merge_group_id"]
        members = sorted(g["members"], key=lambda m: m["candidate_id"])
        rep = g["representative"]
        rep_cid = rep["candidate_id"]
        real = cand_by_id[rep_cid]
        snapshot = {"value": rep.get("value"), "basis": rep.get("basis"),
                    "confidence": rep.get("confidence")}
        stale = (real["claim"]["value"] != rep.get("value")
                 or real["claim"]["basis"] != rep.get("basis")
                 or real.get("confidence") != rep.get("confidence"))
        if stale:
            warnings.append(f"group {gid} representative snapshot 与候选不一致 (snapshot_stale)")
        # provenance
        srcs = set()
        for m in members:
            c = cand_by_id[m["candidate_id"]]
            srcs.update(c.get("source_refs", []))
        groups.append({
            "merge_group_id": gid,
            "members": members,
            "representative": {
                "candidate_id": rep_cid,
                "snapshot": snapshot,
                "snapshot_stale": stale,
            },
            "group_confidence": max((cand_by_id[m["candidate_id"]].get("confidence") or 0.0)
                                    for m in members) if members else 0.0,
            "provenance": {
                "candidate_ids": [m["candidate_id"] for m in members],
                "source_refs": sorted(srcs),
            },
        })
    groups.sort(key=lambda g: g["merge_group_id"])
    resolved_relations.sort(key=lambda r: r["relation_id"])

    # ---- corrections 定位 ----
    pending_corrections: List[dict] = []
    for corr in (corrections or []):
        ck = corr.get("target_kind")
        tid = corr.get("target_id")
        if ck == "candidate":
            if tid in cand_by_id:
                rt = {"kind": "candidate", "candidate_id": tid,
                      "group_id": candidate_to_group.get(tid)}
            else:
                rt = {"kind": "unresolvable_in_this_batch", "candidate_id": None,
                      "group_id": None}
                warnings.append(f"correction {corr.get('id')} target candidate {tid} 不在本批")
        else:  # persona_claim / memory_item
            rt = {"kind": "belongs_to_5_5", "candidate_id": None, "group_id": None}
        pending_corrections.append({
            "correction_id": corr.get("id"),
            "target_kind": ck,
            "target_id": tid,
            "target_path": corr.get("target_path"),
            "user_statement": corr.get("user_statement"),
            "corrected_value": corr.get("corrected_value"),
            "resolved_target": rt,
            "status": corr.get("status", "active"),
        })
    pending_corrections.sort(key=lambda c: c["correction_id"] or "")

    discarded = sorted(merge_result.get("discarded_candidate_ids", []))
    # discarded 不得进入 candidate_to_group
    discarded_set = set(discarded)
    for cid in list(candidate_to_group):
        if cid in discarded_set:
            # 防御：5.3 保证 discarded 不进组；若出现即输入污染
            errors.append(f"discarded candidate {cid} 出现在 group 中（输入污染）")

    candidate_count = len([c for c in candidate_set.get("candidates", [])
                           if c.get("status", "pending") != "discarded"])
    stats = {
        "group_count": len(groups),
        "candidate_count": candidate_count,
        "relation_count": len(resolved_relations),
        "group_relation_count": len(group_level_relations),
        "unresolved_pair_count": len(unresolved),   # 单侧，非虚构 pair
        "pending_correction_count": len(pending_corrections),
    }

    bundle = {
        "schema_version": "1.0",
        "input_refs": {
            "candidate_set_schema_version": candidate_set.get("schema_version", "1.0"),
            "merge_schema_version": merge_result.get("schema_version", "1.0"),
        },
        "groups": groups,
        "group_level_relations": group_level_relations,
        "resolved_relations": resolved_relations,
        "unresolved": unresolved,
        "discarded_candidate_ids": discarded,
        "pending_corrections": pending_corrections,
        "candidate_to_group": dict(sorted(candidate_to_group.items())),
        "stats": stats,
    }
    if errors:
        return {"ok": False, "bundle": None,
                "errors": ["输入污染: " + "; ".join(errors[:10])], "warnings": warnings}
    b_errs = _schema_errs(_validator(BUNDLE_SCHEMA_PATH), bundle)
    if b_errs:
        return {"ok": False, "bundle": None,
                "errors": ["bundle schema 校验失败: " + b_errs[0]], "warnings": warnings}
    return {"ok": True, "bundle": bundle, "errors": [], "warnings": warnings}


def _flip_direction(d: Optional[str]) -> Optional[str]:
    if d == "a_earlier_b_later":
        return "b_earlier_a_later"
    if d == "b_earlier_a_later":
        return "a_earlier_b_later"
    if d == "a_corrects_b":
        return "b_corrects_a"
    if d == "b_corrects_a":
        return "a_corrects_b"
    return d


def bundle_summary(bundle: dict) -> dict:
    return {
        "stats": bundle["stats"],
        "groups": [{"id": g["merge_group_id"],
                    "members": [m["candidate_id"] for m in g["members"]]}
                   for g in bundle["groups"]],
        "group_relations": [{"a": r["group_a"], "b": r["group_b"], "type": r["relation_type"],
                             "advisory": r["advisory"]} for r in bundle["group_level_relations"]],
    }


# ---------------------------------------------------------------------------
# CLI（诊断）
# ---------------------------------------------------------------------------
def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="ResolvedEvidenceBundle（诊断）")
    ap.add_argument("--candidate-set", required=True)
    ap.add_argument("--merge-result", required=True)
    ap.add_argument("--corrections", default=None)
    ap.add_argument("--output", default=None)
    args = ap.parse_args(argv)
    cs = json.load(open(args.candidate_set, encoding="utf-8"))
    mr = json.load(open(args.merge_result, encoding="utf-8"))
    corrs = None
    if args.corrections:
        corrs = json.load(open(args.corrections, encoding="utf-8"))
    r = resolve_bundle(candidate_set=cs, merge_result=mr, corrections=corrs)
    if not r["ok"]:
        print("ERROR:", r["errors"])
        return 2
    print(json.dumps(bundle_summary(r["bundle"]), ensure_ascii=False, indent=2))
    for w in r["warnings"]:
        print("WARN:", w)
    if args.output:
        json.dump(r["bundle"], open(args.output, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2, sort_keys=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
