#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Evidence Merge（Stage 5.3）：Evidence Candidate → Merge Groups + Relations

本层只负责：候选间关系判定、merge group 构建、provenance 保留。
不裁决最终 Persona/Memory、不删除任何候选、不执行 correction overlay、
不修改 Persona/Memory。

硬约束：
  - Blocking 仅作性能优化，不作语义判断：跨桶 = "本轮未比较"，不产生 relation，
    绝不因跨桶输出 unrelated。
  - Union-Find 只使用 same / supporting_same_core 边；supporting_related/conflict/
    temporal_evolution/correction_relation/unresolved 不入并查集。
  - relation 只包含实际判定过的对；A-B、B-C 同组不自动生成 A-C relation。
  - representative 必须是组内已有 candidate 的确定性派生，绝不综合改写新事实。
  - user_narration 三不变量（speaker=user/basis=user_report_only/source_type∈
    {user_narration,user_input}）永不改变。
  - candidate 原字段只读：merge 不修改候选。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import unicodedata
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

try:
    from evidence_extractor import canonicalize_claim, validate_candidate_set
except Exception:  # pragma: no cover
    canonicalize_claim = None
    validate_candidate_set = None

SCHEMA_VERSION = "1.0"
MERGE_SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "merge_group.schema.json")
CAND_SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "evidence_candidate.schema.json")


class MergeError(Exception):
    """Merge 层错误（可诊断）。"""


# ---------------------------------------------------------------------------
# 校验器
# ---------------------------------------------------------------------------
_VALIDATOR = None


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


_merge_validator = None
_cand_validator = None


def _get_validators():
    global _merge_validator, _cand_validator
    if _merge_validator is None:
        _merge_validator = _load_validator(MERGE_SCHEMA_PATH)
        _cand_validator = _load_validator(CAND_SCHEMA_PATH)
    return _merge_validator, _cand_validator


def validate_merge_result(data: dict) -> List[str]:
    mv, _ = _get_validators()
    return [f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in mv.iter_errors(data)]


# ---------------------------------------------------------------------------
# 确定性辅助
# ---------------------------------------------------------------------------
def _is_iso(v) -> bool:
    try:
        datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


_NEG_PATTERNS = [
    r"不", r"没", r"没[有用]", r"从不", r"不再", r"讨厌", r"反感", r"戒了", r"不喝",
    r"不吃", r"不喜欢", r"不要", r"否认", r"并不", r"并非", r"从不喝", r"戒掉",
]


def _polarity(value: str) -> int:
    """简单确定性极性：含否定/厌恶词 → -1（负向），否则 +1（正向）。仅启发式，模糊交 LLM。"""
    s = value or ""
    neg_hit = any(re.search(p, s) for p in _NEG_PATTERNS)
    return -1 if neg_hit else 1


def _strip_time(value: str) -> str:
    """剥离前导时间短语（仅当确实是时间前缀），便于同核比较。确定性启发式。

    只剥白名单形态，避免误吞正文（如"她喜欢猫"绝不能因 CJK 前缀被剥空）：
      ^(20NN|19NN)年?      → "2022年" / "2025"
      ^N月N日              → "6月1日"
      ^昨天/今天/前天…      → "昨天"
    不在白名单的前缀一律保留。
    """
    s = value or ""
    m = re.match(r"^(?:(20\d{2}|19\d{2})年?|\d{1,2}月\d{1,2}日|昨天|今天|前天(?:晚上|白天|中午|早上)?)", s)
    if m:
        return s[m.end():]
    return s


def core_key(value: str) -> str:
    """core-normalized：去时间前缀 + canonical。用于 same-core 比较。"""
    return canonicalize_claim(_strip_time(value))


# ---------------------------------------------------------------------------
# 常量排序
# ---------------------------------------------------------------------------
_BASIS_RANK = {"direct_quote": 5, "multi_evidence": 4, "single_weak": 3,
               "user_report_only": 2, "inferred": 1, "correction": 0}
_ETYPE_RANK = {"target_message": 5, "user_correction": 4, "social_post": 3,
               "photo_exif": 2, "user_narration": 1}
_REL_ORDER = ["same", "supporting_same_core", "supporting_related", "conflict",
              "temporal_evolution", "correction_relation", "unresolved", "unrelated"]


# ---------------------------------------------------------------------------
# ID
# ---------------------------------------------------------------------------
def _sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8", "surrogatepass")).hexdigest()


def compute_relation_id(a_id: str, b_id: str, rel_type: str) -> str:
    pair = "\x1f".join(sorted([a_id, b_id]))
    return "rel_" + _sha1(pair + "\x1f" + rel_type)[:16]


def compute_merge_group_id(primary_candidate: dict) -> str:
    ck = core_key(primary_candidate["claim"]["value"])
    return "mg_" + _sha1(ck)[:16]


# ---------------------------------------------------------------------------
# blocking（仅性能）
# ---------------------------------------------------------------------------
def _block_tokens(value: str) -> List[str]:
    """blocking 用主题词（多桶索引）。每个候选按词进多个桶，避免因桶切分漏掉应比较的对。"""
    s = core_key(value)
    toks = []
    for ch in s:
        if "一" <= ch <= "鿿" and ch not in ("她", "他", "我", "的", "了", "是", "在", "说", "很", "不", "没", "会", "想"):
            toks.append(ch)
    return sorted(set(toks)) or [s]


# ---------------------------------------------------------------------------
# Union-Find（仅 same / supporting_same_core 边）
# ---------------------------------------------------------------------------
class _UF:
    def __init__(self):
        self.parent: Dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra

    def groups(self) -> Dict[str, List[str]]:
        out: Dict[str, List[str]] = {}
        for x in self.parent:
            out.setdefault(self.find(x), []).append(x)
        return out


# ---------------------------------------------------------------------------
# primary 确定性选择
# ---------------------------------------------------------------------------
def pick_primary(member_ids: List[str], cand_by_id: Dict[str, dict]) -> str:
    """basis_rank → confidence → evidence_type_rank → -len(value) → candidate_id。全序。"""
    def sort_key(cid: str):
        c = cand_by_id[cid]
        b = c["claim"]["basis"]
        return (-_BASIS_RANK.get(b, 0),            # 高 basis rank 优先 → 负数使大的排前
                -(c.get("confidence") or 0.0),      # 高 confidence 优先
                -_ETYPE_RANK.get(c.get("evidence_type", ""), 0),
                len(c["claim"]["value"]),            # 短 value 优先（精炼）
                cid)                                 # tie-break：确定性 id
    return sorted(member_ids, key=sort_key)[0]


# ---------------------------------------------------------------------------
# 关系判定
# ---------------------------------------------------------------------------
def _cmp_time_earlier(a: dict, b: dict) -> Optional[bool]:
    """返回 a 是否早于 b；无法确定返回 None。"""
    def t_of(c: dict):
        tp = c.get("time_period")
        if tp and isinstance(tp, dict) and tp.get("from"):
            return tp["from"].get("value"), tp["from"].get("precision")
        if c.get("observed_at"):
            return c["observed_at"], "exact"
        return None, None
    ta, pa = t_of(a)
    tb, pb = t_of(b)
    if not ta or not tb:
        return None
    # 归一化字符串比较：要求格式近似 ISO 或 "YYYY年"
    def norm(v):
        v = str(v)
        v = v.replace("年", "-").replace("月", "-").replace("日", "")
        v = v.strip(" -").rstrip("-")
        return v
    na, nb = norm(ta), norm(tb)
    try:
        # 长度补齐比较（YYYY 与 YYYY-MM 混比取前缀）
        if na == nb:
            return None
        return na < nb
    except Exception:
        return None


def _same_core_pair(a: dict, b: dict) -> bool:
    """same-core：canonical 等价。无 LLM 时 canonical 不等绝不判 same_core。"""
    return core_key(a["claim"]["value"]) == core_key(b["claim"]["value"])


def classify_pair(a: dict, b: dict, *, llm: Optional[Callable] = None) -> dict:
    """判定一对候选的关系（确定性优先，LLM 仅在不确定带）。

    优先级：exact→correction→temporal→conflict→same-core→related→unresolved。
    返回 {relation_type, direction, relation_confidence, basis_method, reason}。
    """
    a_id, b_id = a["candidate_id"], b["candidate_id"]
    av, bv = a["claim"]["value"], b["claim"]["value"]

    # 1) exact same
    if canonicalize_claim(av) == canonicalize_claim(bv):
        return {"relation_type": "same", "direction": None,
                "relation_confidence": 1.0, "basis_method": "canonical_exact",
                "reason": "canonical 等价"}

    # 2) explicit correction
    a_corr = a.get("evidence_type") == "user_correction"
    b_corr = b.get("evidence_type") == "user_correction"
    if a_corr or b_corr:
        direction = "a_corrects_b" if a_corr else "b_corrects_a"
        return {"relation_type": "correction_relation", "direction": direction,
                "relation_confidence": 0.9, "basis_method": "negation_polarity",
                "reason": "存在 user_correction 候选"}

    # 能走到这里说明两候选共享至少一个 blocking 主题词（已实际比较）。
    # 同主题内按 极性 → same-core 判定。跨桶（无共享词）的候选根本不进本轮比较 → 无 relation，
    # 绝不会被误判为 unrelated。
    pa, pb = _polarity(av), _polarity(bv)
    same_core = _same_core_pair(a, b)

    if same_core:
        return {"relation_type": "supporting_same_core", "direction": None,
                "relation_confidence": 0.95, "basis_method": "semantic",
                "reason": "同核心命题（去时间 canonical 等价）"}

    if pa != pb:
        # 极性相反：时间可排序 → temporal_evolution；否则 conflict
        earlier = _cmp_time_earlier(a, b)
        if earlier is not None:
            direction = "a_earlier_b_later" if earlier else "b_earlier_a_later"
            return {"relation_type": "temporal_evolution", "direction": direction,
                    "relation_confidence": 0.8, "basis_method": "temporal",
                    "reason": "同主题极性相反且时间可排序，判为时间演变"}
        return {"relation_type": "conflict", "direction": None,
                "relation_confidence": 0.8, "basis_method": "negation_polarity",
                "reason": "同主题极性相反且无时间顺序，判为冲突"}

    # 同主题同极性，canonical 不等：无 LLM → related（不擅自 same_core）
    if llm is not None:
        # LLM adjudication：仅判定 same_core vs related，不修改候选字段
        r = _llm_adjudicate(a, b, llm)
        if r is not None:
            return r
        return {"relation_type": "unresolved", "direction": None,
                "relation_confidence": 0.3, "basis_method": "llm_adjudication",
                "reason": "LLM 无法判定，安全降级 unresolved"}
    return {"relation_type": "supporting_related", "direction": None,
            "relation_confidence": 0.5, "basis_method": "semantic",
            "reason": "同主题同极性但 canonical 不等：related-but-distinct（不并组）"}


def _llm_adjudicate(a: dict, b: dict, llm: Callable) -> Optional[dict]:
    """LLM 只判 same_core vs related；返回 None = 无法判定 → 上层 unresolved。"""
    prompt = (
        "判断两条证据候选是否属于【同一核心事实】（same_core）还是【相关但不同事实】（related）。\n"
        "候选A: " + json.dumps({"value": a["claim"]["value"], "speaker": a["speaker_role"],
                                 "basis": a["claim"]["basis"], "time": a.get("observed_at")},
                                ensure_ascii=False) + "\n"
        "候选B: " + json.dumps({"value": b["claim"]["value"], "speaker": b["speaker_role"],
                                 "basis": b["claim"]["basis"], "time": b.get("observed_at")},
                                ensure_ascii=False) + "\n"
        "只输出 JSON: {\"relation_type\": \"same_core\"|\"related\", \"reason\": \"...\"}"
    )
    try:
        raw = llm(prompt)
    except Exception:
        return None
    m = re.search(r"\{[\s\S]*\}", raw or "")
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    rt = obj.get("relation_type")
    if rt == "same_core":
        return {"relation_type": "supporting_same_core", "direction": None,
                "relation_confidence": 0.85, "basis_method": "llm_adjudication",
                "reason": obj.get("reason") or "LLM 判 same_core"}
    if rt == "related":
        return {"relation_type": "supporting_related", "direction": None,
                "relation_confidence": 0.6, "basis_method": "llm_adjudication",
                "reason": obj.get("reason") or "LLM 判 related"}
    return None


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def merge_evidence(*, candidates: List[dict], llm: Optional[Callable] = None) -> dict:
    """候选集 → MergeResult。

    输入 candidates：dict 列表，需通过 evidence_candidate.schema v1.0。
    返回 {ok, merge_result, errors, warnings}。
    """
    errors: List[str] = []
    warnings: List[str] = []

    # A. schema gate
    cand_set = {"schema_version": "1.0", "extraction_context": {}, "candidates": candidates}
    if validate_candidate_set is not None:
        verrs = validate_candidate_set(cand_set)
        if verrs:
            return {"ok": False, "merge_result": None,
                    "errors": ["输入 candidate 集 schema 校验失败: " + verrs[0]
                               + (f" (+{len(verrs)-1})" if len(verrs) > 1 else "")],
                    "warnings": warnings}

    cand_by_id = {c["candidate_id"]: c for c in candidates}
    # 去重（同 candidate_id 重复输入）
    seen = set()
    uniq = []
    for c in candidates:
        if c["candidate_id"] not in seen:
            seen.add(c["candidate_id"])
            uniq.append(c)
        else:
            warnings.append(f"重复 candidate_id {c['candidate_id']}，已去重")
    candidates = uniq

    active = [c for c in candidates if c.get("status", "pending") != "discarded"]
    discarded_ids = [c["candidate_id"] for c in candidates if c.get("status", "pending") == "discarded"]

    # B. blocking（仅性能优化，多桶倒排索引）：共享任一主题词的候选才进入比较候选池。
    #    跨桶不是"unrelated"结论——只表示未进入本轮比较；无 relation。
    buckets: Dict[str, List[dict]] = {}
    for c in active:
        for tok in _block_tokens(c["claim"]["value"]):
            buckets.setdefault(tok, []).append(c)

    # 候选池：有共享主题词的配对（去重）
    candidates_to_compare: set = set()
    for members in buckets.values():
        if len(members) < 2:
            continue
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                a, b = members[i], members[j]
                candidates_to_compare.add(tuple(sorted([a["candidate_id"], b["candidate_id"]])))

    # C. 对候选池内每一对做实际判定
    uf = _UF()
    relations_by_type: Dict[Tuple[str, str], dict] = {}   # (a,b) -> rel
    unresolved_ids: List[str] = []
    compared_pairs: set = set()
    cand_by_cid = {c["candidate_id"]: c for c in active}

    def add_relation(a: dict, b: dict, res: dict):
        a_id, b_id = a["candidate_id"], b["candidate_id"]
        rel_id = compute_relation_id(a_id, b_id, res["relation_type"])
        key = tuple(sorted([a_id, b_id]))
        if key in relations_by_type:
            return
        rel = {
            "relation_id": rel_id,
            "source_a": {"kind": "candidate", "id": a_id},
            "source_b": {"kind": "candidate", "id": b_id},
            "relation_type": res["relation_type"],
            "relation_confidence": res["relation_confidence"],
            "direction": res.get("direction"),
            "basis_method": res.get("basis_method", "semantic"),
            "reason": res.get("reason"),
            "created_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        }
        relations_by_type[key] = rel
        compared_pairs.add(key)
        # Union-Find 仅 same / supporting_same_core
        if res["relation_type"] in ("same", "supporting_same_core"):
            uf.union(a_id, b_id)

    for a_id, b_id in sorted(candidates_to_compare):
        a, b = cand_by_cid[a_id], cand_by_cid[b_id]
        res = classify_pair(a, b, llm=llm)
        if res["relation_type"] == "unresolved":
            # 无法定类：不建立 relation，仅记录待审
            unresolved_ids.extend([a_id, b_id])
            continue
        add_relation(a, b, res)

    # D. 建组：每个 active candidate 恰在一个组（same/same_core 连通块；孤点成单成员组）
    uf_groups = uf.groups()
    assigned = set()
    ordered_groups = []
    # 先把 union 出的连通块作为组
    for members in uf_groups.values():
        mlist = sorted(set(members))
        ordered_groups.append(mlist)
        assigned.update(mlist)
    # 孤点（未进入任何 same/same_core 边的 active 候选）各自成组
    for c in active:
        cid = c["candidate_id"]
        if cid not in assigned:
            ordered_groups.append([cid])
            assigned.add(cid)

    groups_out = []
    for members in ordered_groups:
        primary_id = pick_primary(members, cand_by_id)
        primary = cand_by_id[primary_id]
        gid = compute_merge_group_id(primary)
        # stats
        srcs = set()
        etype_mix = {}
        for mid in members:
            c = cand_by_id[mid]
            for s in c.get("source_refs", []):
                srcs.add(s)
            et = c.get("evidence_type", "?")
            etype_mix[et] = etype_mix.get(et, 0) + 1
        # has_conflict：组内任一成员参与了 conflict/temporal relation
        has_conflict = False
        for (ka, kb), rel in relations_by_type.items():
            if rel["relation_type"] in ("conflict", "temporal_evolution"):
                if ka in members or kb in members:
                    has_conflict = True
                    break
        groups_out.append({
            "merge_group_id": gid,
            "representative": {
                "candidate_id": primary_id,
                "value": primary["claim"]["value"],
                "basis": primary["claim"]["basis"],
                "confidence": primary.get("confidence") or 0.0,
            },
            "members": [{"candidate_id": m,
                         "role_in_group": "primary" if m == primary_id else "supporting_same_core"}
                        for m in members],
            "stats": {
                "independent_support_count": len(members),
                "source_diversity": len(srcs),
                "has_conflict": has_conflict,
                "evidence_type_mix": etype_mix,
            },
            "relations": [],
            "created_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        })

    # E. relation 端点保持在 candidate 层（可经 group.members 解析到所属 merge_group）
    #    确定性输出顺序：groups 按 merge_group_id、relations 按 relation_id 排序（不依赖输入顺序）
    groups_out.sort(key=lambda g: g["merge_group_id"])
    relations_out = sorted(relations_by_type.values(), key=lambda r: r["relation_id"])
    unresolved_ids = sorted(set(unresolved_ids))

    merge_result = {
        "schema_version": SCHEMA_VERSION,
        "groups": groups_out,
        "relations": relations_out,
        "discarded_candidate_ids": sorted(discarded_ids),
        "unresolved_candidate_ids": unresolved_ids,
        "stats": {
            "input_candidates": len(candidates),
            "grouped_candidates": len([c for c in candidates if c.get("status", "pending") != "discarded"]),
            "group_count": len(groups_out),
            "relation_count": len(relations_out),
            "discarded": len(discarded_ids),
            "unresolved": len(unresolved_ids),
        },
    }
    merrs = validate_merge_result(merge_result)
    if merrs:
        return {"ok": False, "merge_result": None,
                "errors": ["merge 输出 schema 校验失败: " + merrs[0]], "warnings": warnings}
    return {"ok": True, "merge_result": merge_result, "errors": errors, "warnings": warnings}


def merge_result_summary(mr: dict) -> dict:
    """简洁摘要（供报告/审计）。"""
    return {
        "group_count": mr["stats"]["group_count"],
        "relation_count": mr["stats"]["relation_count"],
        "groups": [{"id": g["merge_group_id"], "members": [m["candidate_id"] for m in g["members"]],
                    "primary": g["representative"]["candidate_id"]} for g in mr["groups"]],
        "relations": [{"id": r["relation_id"], "a": r["source_a"]["id"], "b": r["source_b"]["id"],
                       "type": r["relation_type"]} for r in mr["relations"]],
    }


# ---------------------------------------------------------------------------
# CLI（诊断）
# ---------------------------------------------------------------------------
def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Evidence Merge（诊断）")
    ap.add_argument("--candidate-set", required=True, help="evidence candidate set JSON")
    ap.add_argument("--output", default=None)
    args = ap.parse_args(argv)
    data = json.load(open(args.candidate_set, encoding="utf-8"))
    cands = data.get("candidates", data if isinstance(data, list) else [])
    r = merge_evidence(candidates=cands)
    if not r["ok"]:
        print("ERROR:", r["errors"])
        return 2
    print(json.dumps(merge_result_summary(r["merge_result"]), ensure_ascii=False, indent=2))
    if args.output:
        json.dump(r["merge_result"], open(args.output, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
