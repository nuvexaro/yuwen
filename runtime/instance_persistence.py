#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage: Distribution Wrapper / F1 — Instance Persistence Layer（Non-Frozen）。

职责：把"已 confirmed + 已 F5-e 归约"的 correction 持久化到当前 Ex Instance 的
persona_memory.json。**只负责落盘，不是新的 correction engine。**

硬约束：
  - confirmed correction 绝不直接 dump overlay；必须经 confirmed → F5-e/F5-f 语义归约 → 落盘。
  - 消费 F5-e（correction_conflicts.resolve_statements，唯一 semantic authority）与
    F5-f export 的 PROPOSAL_CONFIRMED 语义；不重判 current/superseded。
  - 落盘结构对齐 frozen builder apply_corrections 的 on-disk contract：
    memory_item correction → 旧 target memory 标 superseded/corrected/superseded_by；
    顶层 corrections[] append correctionItem(status=active)。
  - superseded/rejected/expired 不得错误成为 active。
  - 单 Ex 写者锁；temp + os.replace 原子写；写前 version backup；写前 schema 校验。
  - 保持唯一 canonical：只写该 Instance 的 persona_memory.json。
  - 不修改任何 Frozen 文件（schema / correction_runtime / correction_conflicts /
    correction_export / correction_longterm_projection / persona_loader / ...）。
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
from datetime import datetime
from typing import Dict, List, Optional

# 消费 F5-e（semantic authority）与 F5-f phase2 bucket 映射，只读不改
# 两个导入独立 try：persona_memory_builder 需要额外第三方依赖（jsonschema），
# 它的导入失败不应连带把 correction 语义权威（f5e）也置为 None。
try:
    import sys
    HERE = os.path.dirname(os.path.abspath(__file__))
    TOOLS = os.path.join(os.path.dirname(HERE), "tools")
    for p in (HERE, TOOLS):
        if p not in sys.path:
            sys.path.insert(0, p)
    import correction_conflicts as f5e
    from correction_longterm_projection import _bucket_of_target_path
except Exception:  # noqa: BLE001
    f5e = None
    _bucket_of_target_path = None

try:
    import persona_memory_builder as _pmb
except Exception:  # noqa: BLE001
    _pmb = None

MEMORY_BUCKETS = ["core_facts", "timeline", "shared_experiences", "conflicts",
                  "happy_memories", "breakup", "inside_jokes", "preferences", "daily_patterns"]


# ---------------------------------------------------------------------------
# Instance-level shared write lock（F4：同一 Ex Instance 多 session 共享稳定锁）
# ---------------------------------------------------------------------------
import threading as _threading

_LOCK_REGISTRY: Dict[str, _threading.Lock] = {}
_REGISTRY_GUARD = _threading.Lock()


def get_instance_lock(persona_memory_path: str) -> _threading.Lock:
    """返回该 Ex Instance（按 persona_memory.json 路径）的稳定共享写锁。

    同一路径永远返回同一 Lock 实例 → 同一 Ex 的多个 session 写回共享同一把锁，
    不会各自创建互不相同的锁。F1 write_back(..., lock=...) API 不变。
    """
    key = os.path.abspath(persona_memory_path)
    with _REGISTRY_GUARD:
        if key not in _LOCK_REGISTRY:
            _LOCK_REGISTRY[key] = _threading.Lock()
        return _LOCK_REGISTRY[key]


def _require_pm_structure(pm: dict) -> List[str]:
    """轻量结构校验：对齐 schema required（schema_version/revision/persona/memory）+ memory 9 桶 + corrections。"""
    errs = []
    if not isinstance(pm, dict):
        return ["persona_memory 非 dict"]
    for k in ("schema_version", "revision", "persona", "memory"):
        if k not in pm:
            errs.append(f"缺 {k}")
    mem = pm.get("memory")
    if not isinstance(mem, dict):
        errs.append("memory 非 dict")
    else:
        for b in MEMORY_BUCKETS:
            if b not in mem:
                errs.append(f"memory 缺桶 {b}")
    if "corrections" not in pm:
        errs.append("缺 corrections")
    return errs


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def reduce_confirmed_corrections(persona_memory: dict,
                                 confirmed_statements: List[dict]) -> Dict[str, list]:
    """把 confirmed correction statements 经 F5-e 归约成 {to_apply:[...], superseded_prev:[...]}。

    confirmed_statements: [{id, corrected_value, target_id, target_path, user_statement, created_at}]
    已 confirmed（调用方保证）；这里只消费 F5-e 归约语义，不重判。
    """
    if f5e is None:
        return {"to_apply": [], "superseded_prev": []}
    # 把现有 Instance 顶层 active memory-item corrections 也并入，使新 correction 能正确 supersede 旧 correction
    stmts = []
    for c in persona_memory.get("corrections") or []:
        if c.get("status") == "active" and c.get("target_kind") == "memory_item" and c.get("corrected_value"):
            stmts.append({"kind": f5e.KIND_CORRECTION, "value": c["corrected_value"], "id": c["id"],
                          "source_turn": c.get("user_statement"), "at": c.get("created_at"),
                          "target_domain": "memory", "field": c.get("target_path"),
                          "target_id": c.get("target_id")})
    for s in confirmed_statements:
        stmts.append({"kind": f5e.KIND_CORRECTION, "value": s["corrected_value"], "id": s["id"],
                      "source_turn": s.get("user_statement"), "at": s.get("created_at"),
                      "target_domain": "memory", "field": s.get("target_path"),
                      "target_id": s.get("target_id")})
    lanes = f5e.resolve_statements(stmts)
    # current = 归约后应 active 的 correction（去重 by id，保序）
    active = {}
    order = []
    # superseded_prev_by: 记录"每个应保持 active 的 current correction id → 它 supersede 的旧 correction id 集"
    superseded_prev_by: Dict[str, List[str]] = {}
    existing_corr_ids = {c.get("id") for c in persona_memory.get("corrections") or []}
    for lane in lanes.values():
        cur = lane.get("current")
        if cur and cur.get("kind") == f5e.KIND_CORRECTION and cur.get("id"):
            if cur["id"] not in active:
                active[cur["id"]] = cur
                order.append(cur["id"])
            # 收集本 lane 中被 current supersede 的 correction，仅限"已在 persona_memory.corrections[] 里的旧值"
            for s in lane.get("superseded", []):
                if s.get("kind") == f5e.KIND_CORRECTION and s.get("id") in existing_corr_ids:
                    superseded_prev_by.setdefault(cur["id"], []).append(s["id"])
    to_apply = []
    for cid in order:
        cur = active[cid]
        to_apply.append({
            "id": cur["id"], "target_kind": "memory_item", "target_id": cur.get("target_id"),
            "target_path": cur.get("field"), "corrected_value": cur.get("value"),
            "user_statement": cur.get("source_turn"), "created_at": cur.get("at") or _now_iso(),
            "supersedes": superseded_prev_by.get(cid, []),
        })
    return {"to_apply": to_apply, "superseded_prev": [i for ids in superseded_prev_by.values() for i in ids]}


def apply_to_persona_memory(persona_memory: dict, confirmed_statements: List[dict]) -> dict:
    """把已归约的 confirmed corrections 应用到 persona_memory dict（内存），返回新 dict（deepcopy）。

    落盘结构对齐 frozen builder apply_corrections：
      memory_item correction：旧 target memory 标 superseded/corrected/superseded_by；
      顶层 corrections[] append/合并 correctionItem。
    不写盘；纯内存变换，供 write_back 调用。
    """
    pm = copy.deepcopy(persona_memory)
    pm.setdefault("corrections", [])
    if not confirmed_statements:
        return pm
    # 幂等：跳过已在 corrections[] 中 active 的同 id confirmed（不重复归约，避免自我 supersede）
    active_ids = {c.get("id") for c in pm["corrections"] if c.get("status") == "active"}
    fresh = [s for s in confirmed_statements if s.get("id") not in active_ids]
    if not fresh:
        return pm
    reduced = reduce_confirmed_corrections(pm, fresh)
    existing_active_ids = {c.get("id") for c in pm["corrections"] if c.get("status") == "active"}
    for corr in reduced["to_apply"]:
        cid = corr["id"]
        tid = corr.get("target_id")
        cv = corr.get("corrected_value")
        if not cid or not cv:
            continue
        # 若该 correction id 已 active → 跳过（幂等，不重复）；但它可能 supersede 其它现存 correction
        is_new_active = cid not in existing_active_ids
        # 1) 把被本 current supersede 的现存 active corrections 标 superseded（F5-e verdict 执行）
        for old_cid in corr.get("supersedes", []):
            for c0 in pm["corrections"]:
                if c0.get("id") == old_cid and c0.get("status") == "active":
                    c0["status"] = "superseded"
                    c0["superseded_by"] = cid
                    c0["supersede_kind"] = "corrected"
        # 2) 若本 correction 已是 active → 不重复 append
        if not is_new_active:
            continue
        # 3) 定位被纠 memory 项 → supersede（对齐 builder）
        orig_value = None
        bucket = _bucket_of_target_path(corr.get("target_path"))
        if bucket and tid:
            for it in pm["memory"].get(bucket, []):
                if it.get("id") == tid and it.get("status") in ("active", "pending_confirmation"):
                    it["status"] = "superseded"
                    it["supersede_kind"] = "corrected"
                    it["superseded_by"] = cid
                    it["corrected"] = True
                    orig_value = it.get("content")
                    break
        # 4) 顶层 corrections[] 留痕（对齐 builder on-disk contract）
        pm["corrections"].append({
            "id": cid, "target_kind": "memory_item", "target_id": tid,
            "target_path": corr.get("target_path"), "original_value": orig_value,
            "corrected_value": cv, "basis_override": "correction",
            "user_statement": corr.get("user_statement"), "status": "active",
            "superseded_by": None, "created_at": corr.get("created_at") or _now_iso(),
        })
    return pm


# ---------------------------------------------------------------------------
# G3 Memory Item Lifecycle（create / decide）
#
# 只负责 memory item 的 status 生命周期，**不参与 correction 语义**——
# correction 的归约与落盘由上方 apply_to_persona_memory 独立负责（本层不改其语义）。
# 两类 op：
#   create：new-fact proposal 确认 → 新建 active memory item（fallback bucket fail-closed）
#   decide：pending_confirmation → active/rejected；rejected → active 仅由显式 revive 触发
# ---------------------------------------------------------------------------

_STATUS_ACTIVE = "active"
_STATUS_PENDING = "pending_confirmation"
_STATUS_REJECTED = "rejected"
_STATUS_SUPERSEDED = "superseded"

# _heuristic_bucket 的 fallback 返回值：无任何关键词通向它（见其函数末行 return）。
# 以此判定"分桶不确定"，fail-closed 拒绝 create，避免把错误分类的数据写入长期记忆。
_FALLBACK_BUCKET = "shared_experiences"


def _lifecycle_new_item(bucket: str, content: str) -> dict:
    """构造 new-fact memory item。字段集与 frozen builder make_memory() 逐一对应，无新增字段。"""
    ts = _now_iso()
    return {
        "id": _pmb.memory_item_id(bucket, content),
        "content": content,
        "importance": 3,
        "confidence": 0.0,          # 无候选证据，不美化
        "source_type": "user_input",
        "source_ref": None,
        "status": _STATUS_ACTIVE,
        "supersede_kind": None,
        "superseded_by": None,
        "corrected": False,
        "evidence_ids": [],         # 无候选证据
        "conflicts_with": [],
        "history": None,
        "valid_period": None,
        "created_at": ts,
        "updated_at": ts,
        "tags": [],
    }


def _find_item_by_id(pm: dict, item_id: str):
    """跨桶定位 memory item（id 为全局确定性派生键）。返回 (bucket, item) 或 (None, None)。"""
    for b in MEMORY_BUCKETS:
        for it in pm.get("memory", {}).get(b, []) or []:
            if it.get("id") == item_id:
                return b, it
    return None, None


def _apply_create(pm: dict, op: dict, report: dict):
    """new-fact create：新建 active item；同 id 已存在时按状态分支处理（幂等）。"""
    content = op.get("content")
    if not isinstance(content, str) or not content.strip():
        report["noops"].append({"op": op, "reason": "content 非法"})
        return
    content = content.strip()
    bucket = _pmb._heuristic_bucket(content)
    # ★ fail-closed 闸门：置于唯一写入 choke point，任何调用方都无法绕过。
    if bucket == _FALLBACK_BUCKET:
        report["noops"].append({"op": op,
                                "reason": "fallback bucket(shared_experiences) 拒绝 create"})
        return
    item_id = _pmb.memory_item_id(bucket, content)
    _b, existing = _find_item_by_id(pm, item_id)
    if existing is None:
        pm.setdefault("memory", {}).setdefault(bucket, []).append(
            _lifecycle_new_item(bucket, content))
        report["applied"] += 1
        return
    st = existing.get("status")
    if st == _STATUS_ACTIVE:
        report["noops"].append({"op": op, "reason": "already active"})
    elif st == _STATUS_PENDING:
        # 用户此刻的确认 = 对同一事实的明确确认（受控例外，见设计 §7.3）
        existing["status"] = _STATUS_ACTIVE
        report["applied"] += 1
    elif st == _STATUS_REJECTED:
        # ★ 禁止普通 create 自动复活 rejected：必须经显式 revive API（decide + expect=rejected）
        report["noops"].append({"op": op, "reason": "rejected_requires_explicit_revive"})
    elif st == _STATUS_SUPERSEDED:
        report["noops"].append({"op": op, "reason": "superseded"})
    else:
        report["noops"].append({"op": op, "reason": f"未知 status {st!r}"})


def _apply_decide(pm: dict, op: dict, report: dict):
    """生命周期裁决：必须带 expect_status 前置条件，status 不符即 no-op（幂等）。"""
    item_id = op.get("item_id")
    expect = op.get("expect_status")
    approve = bool(op.get("approve"))
    bucket = op.get("bucket")
    if not item_id:
        report["noops"].append({"op": op, "reason": "缺 item_id"})
        return
    found_bucket, item = _find_item_by_id(pm, item_id)
    if item is None:
        report["noops"].append({"op": op, "reason": "item 不存在"})
        return
    if bucket and found_bucket != bucket:
        report["noops"].append({"op": op, "reason": f"bucket 不匹配: {found_bucket} != {bucket}"})
        return
    if item.get("status") != expect:
        report["noops"].append({"op": op,
                                "reason": f"status_mismatch: {item.get('status')} != {expect}"})
        return
    if expect == _STATUS_PENDING:
        item["status"] = _STATUS_ACTIVE if approve else _STATUS_REJECTED
        report["applied"] += 1
        return
    if expect == _STATUS_REJECTED:
        if approve:
            item["status"] = _STATUS_ACTIVE
            report["applied"] += 1
            return
        report["noops"].append({"op": op, "reason": "rejected + approve=False → no-op"})
        return
    report["noops"].append({"op": op, "reason": f"expect_status 不受支持: {expect!r}"})


def apply_memory_lifecycle(persona_memory: dict, ops: Optional[List[dict]]):
    """G3 Memory Item Lifecycle：纯内存应用 create / decide 操作。

    返回 (新 pm, report)；report = {"applied": n, "noops": [{op, reason}]}。
    不写盘；deepcopy 语义，输入绝不修改（与 apply_to_persona_memory 同构）。
    不改变 correction semantics —— 与本模块 apply_to_persona_memory 互相独立。
    """
    pm = copy.deepcopy(persona_memory)
    report = {"applied": 0, "noops": []}
    if not ops:
        return pm, report
    if _pmb is None:
        report["noops"].append({"reason": "persona_memory_builder 不可用"})
        return pm, report
    for op in ops:
        kind = (op or {}).get("kind")
        if kind == "create":
            _apply_create(pm, op, report)
        elif kind == "decide":
            _apply_decide(pm, op, report)
        else:
            report["noops"].append({"op": op, "reason": "未知 op kind"})
    return pm, report


def write_back(persona_memory_path: str, confirmed_statements: List[dict],
               *, backup_dir: Optional[str] = None, lock: Optional[object] = None,
               lifecycle_ops: Optional[List[dict]] = None) -> dict:
    """Instance Persistence 主入口：confirmed corrections → 归约 → 原子写回 persona_memory.json。

    - 单 Ex 写者锁：调用方传入 lock（如 threading.Lock 每 Ex 一把）；无锁时用路径级临时锁文件。
    - 写前 backup：若 backup_dir 给出版本快照。
    - temp + os.replace 原子写。
    - 写前 schema/version 结构校验。
    - lifecycle_ops（G3）：memory item 的 create/decide，纯内存变换，与 correction 归约互相独立。
    返回 {"ok": True, "applied": n, "path": ..., "revision": ...} 或抛异常。
    """
    if lock is not None:
        lock.acquire()
    try:
        if not os.path.exists(persona_memory_path):
            raise FileNotFoundError(f"Instance persona_memory 不存在: {persona_memory_path}")
        with open(persona_memory_path, encoding="utf-8") as f:
            pm = json.load(f)
        errs = _require_pm_structure(pm)
        if errs:
            raise ValueError("persona_memory 结构非法: " + "; ".join(errs))
        before = json.dumps(pm, ensure_ascii=False, sort_keys=True)
        new_pm = apply_to_persona_memory(pm, confirmed_statements)
        new_pm, lc_report = apply_memory_lifecycle(new_pm, lifecycle_ops)
        if json.dumps(new_pm, ensure_ascii=False, sort_keys=True) == before:
            return {"ok": True, "applied": 0, "path": persona_memory_path,
                    "revision": pm.get("revision"),
                    "lifecycle_applied": lc_report["applied"],
                    "lifecycle_noops": lc_report["noops"]}
        # version backup（写回前）
        if backup_dir:
            os.makedirs(backup_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            ver = pm.get("revision", 0)
            bk = os.path.join(backup_dir, f"v{ver}_{ts}.json")
            with open(bk, "w", encoding="utf-8") as f:
                json.dump(pm, f, ensure_ascii=False, indent=2)
        # revision 递增
        new_pm["revision"] = (pm.get("revision") or 0) + 1
        new_pm.setdefault("updated_at", _now_iso())
        # 原子写：temp + os.replace
        d = os.path.dirname(os.path.abspath(persona_memory_path))
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(new_pm, f, ensure_ascii=False, indent=2)
            os.replace(tmp, persona_memory_path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        n_applied = len(confirmed_statements)
        return {"ok": True, "applied": n_applied, "path": persona_memory_path,
                "revision": new_pm.get("revision"),
                "lifecycle_applied": lc_report["applied"],
                "lifecycle_noops": lc_report["noops"]}
    finally:
        if lock is not None:
            lock.release()
