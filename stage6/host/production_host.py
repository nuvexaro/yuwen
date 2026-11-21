#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 6.1 — Production Host Skeleton（Non-Frozen，repo 内可运行契约参考实现）。

Host 只做 orchestration / I/O / session lifecycle / adapter injection / correction
confirmation / error handling。**不重新实现** persona semantics / correction authority /
memory authority / retrieval / A′ / F5-e/f。

Canonical：exes/{slug}/persona_memory.json（唯一）
Runtime：persona_loader → PersonaRuntime
Persistence：instance_persistence（唯一写回路径）
Session：session_store（非 canonical）

本文件是 host 骨架（reference，可在本地用 real adapter 跑真实 E2E）；不作为 fake
production deployment 冒充已上线系统。multi-process 需更强锁 = 已记录风险，未引入。
"""

from __future__ import annotations

import json
import os
import re
import sys
import uuid
from typing import Callable, Dict, List, Optional

# --- path setup: allow import of repo runtime/tools ---
_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.join(_HERE, "..", ".."), os.path.join(_HERE, "..", "..", "runtime"),
           os.path.join(_HERE, "..", "..", "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class HostError(Exception):
    """Host 层错误基类。"""


class ExNotFound(HostError):
    pass


class InvalidSlug(HostError):
    pass


class MalformedPersonaMemory(HostError):
    pass


class ProviderError(HostError):
    pass


class SessionSaveError(HostError):
    pass


class PersistError(HostError):
    pass


_SLUG_RE = re.compile(r"[a-z0-9][a-z0-9\-_]{0,40}")


def _require_slug(slug: str) -> str:
    if not slug or not _SLUG_RE.fullmatch(slug):
        raise InvalidSlug(f"非法 slug: {slug!r}")
    return slug


# ---------- R5: 输出边界抑制舞台/动作描写（product surface；不改 runtime 语义）----------
# 真实现象（真实 Pilot 记录 stage6/cli/pilot_data/sessions/5f7be9e4/test01/732a63bcc897.json）：
#   「（挑眉）哦？…」「（放下奶茶杯）还行吧…」「（叼着吸管笑）怎么…」「（放下手机，轻笑一声）那要看…」
# 规则刻意保守（不粗暴删除所有括号内容）：
#   1) 只处理回复【开头】的括号组 —— 实测泄漏形态全部出现在开头；
#   2) 括号内含句末标点（。！？…~）→ 不视为动作，原样保留；
#   3) 括号内不含任何字母（如「（2023）」「（3+5）」）→ 不视为动作，保留（避免误伤数学/纯符号）；
#   4) 剥完为空 → 回退原文，绝不产出空回复。
# 因 runtime 自身 fallback（「……（先不说这个了。）」）不以（ 开头，规则 1 天然不触及它们。
_STAGE_LEAD_RE = re.compile(r"^[ \t]*(?:[（(][^（）()]{1,20}[）)][ \t]*)+")
_STAGE_GROUP_RE = re.compile(r"[（(]([^（）()]*)[）)]")
_SENT_FINAL_RE = re.compile(r"[。！？!?…~～]")
_HAS_LETTER_RE = re.compile(r"[^\W\d_]", re.UNICODE)


def _strip_stage_directions(text):
    """抑制回复开头的舞台/动作描写。规则见上方注释；非 str/空输入原样返回。"""
    if not isinstance(text, str) or not text:
        return text
    m = _STAGE_LEAD_RE.match(text)
    if not m:
        return text
    groups = _STAGE_GROUP_RE.findall(m.group(0))
    if not groups or any(_SENT_FINAL_RE.search(g) for g in groups):
        return text
    if not all(_HAS_LETTER_RE.search(g) for g in groups):
        return text
    rest = text[m.end():].lstrip()
    return rest if rest else text


class Host:
    """单进程 Production Host Skeleton。

    职责：定位 Ex、管理 session、构造 runtime、多轮编排、correction 确认边界、
    持久化触发、Ex 切换、错误/retry。
    """

    def __init__(self, base_dir: str, *, adapter: Optional[Callable] = None,
                 model: str = "mock", retry_transient: int = 2,
                 session_store_dir: Optional[str] = None):
        self.base_dir = base_dir
        self.adapter = adapter            # real adapter injected by caller; None -> mock (unit only)
        self.model = model
        self.retry_transient = retry_transient
        self.session_store_dir = session_store_dir
        self._runtimes: Dict[str, object] = {}   # slug -> runtime (lazy)
        self._sessions: Dict[str, dict] = {}     # session_id -> {"slug": str}
        self._slug_stores: Dict[str, object] = {}  # slug -> SessionStore（跨 runtime 存活）
        self._runtime_dirty: set = set()         # slug 需 force_reload（canonical 已更新）
        self.event_log: List[dict] = []          # telemetry placeholder (host event interface)

    # ---------- Ex resolution ----------
    def resolve_ex(self, slug: str) -> str:
        slug = _require_slug(slug)
        pm_path = os.path.join(self.base_dir, slug, "persona_memory.json")
        if not os.path.exists(pm_path):
            raise ExNotFound(f"Ex 不存在: {slug}")
        return pm_path

    def _load_canonical(self, slug: str) -> dict:
        pm_path = self.resolve_ex(slug)
        try:
            with open(pm_path, encoding="utf-8") as f:
                pm = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            raise MalformedPersonaMemory(f"persona_memory 读取失败: {e}") from e
        # 最小结构校验
        if not isinstance(pm, dict) or not all(k in pm for k in ("schema_version", "persona", "memory")):
            raise MalformedPersonaMemory("persona_memory 结构非法")
        return pm

    # ---------- Runtime construction ----------
    def _store_for_slug(self, slug: str):
        """该 slug 的 SessionStore（所有 session 按 session_id 存于此），按 slug 缓存。

        独立于 runtime（runtime rebuild 不清空 session 数据）。
        file-backed 时 SessionStore(dir) 每次从磁盘重载；内存时缓存同一实例。
        """
        if slug in self._slug_stores:
            return self._slug_stores[slug]
        from session_store import SessionStore
        store_dir = None
        if self.session_store_dir:
            store_dir = os.path.join(self.session_store_dir, slug)
        store = SessionStore(dir=store_dir)
        self._slug_stores[slug] = store
        return store

    def get_runtime(self, slug: str, *, force_reload: bool = False):
        slug = _require_slug(slug)
        dirty = slug in self._runtime_dirty
        if not force_reload and not dirty and slug in self._runtimes:
            return self._runtimes[slug]
        from persona_loader import load_runtime_persona
        from persona_runtime import PersonaRuntime
        from llm_gateway import LLMGateway
        pm_path = self.resolve_ex(slug)
        with open(pm_path, encoding="utf-8") as f:
            longterm = json.load(f)
        base = load_runtime_persona(longterm, None)  # 每次从当前 canonical 重建 base
        gw = LLMGateway(adapter=self.adapter, model=self.model)
        # 用该 slug 的 file-backed store（session 数据跨 runtime 存活）
        store = self._store_for_slug(slug)
        rt = PersonaRuntime(persona_memory=base, gateway=gw, session_store=store)
        self._runtimes[slug] = rt
        self._runtime_dirty.discard(slug)
        return rt

    # ---------- Session lifecycle ----------
    def new_session(self, slug: str) -> str:
        slug = _require_slug(slug)
        self.resolve_ex(slug)  # 校验 Ex 存在
        sid = uuid.uuid4().hex[:12]
        self.get_runtime(slug)  # 确保 runtime + 共享 store 就绪
        self._sessions[sid] = {"slug": slug}
        self._log("session_create", {"session_id": sid, "slug": slug})
        return sid

    def session_slug(self, session_id: str) -> str:
        if session_id not in self._sessions:
            raise HostError(f"未知 session: {session_id}")
        return self._sessions[session_id]["slug"]

    def attach_session(self, slug: str, session_id: str) -> str:
        """把已知 session_id 重新绑定到某 slug（用于 Host 重启/跨实例恢复 file-backed session）。

        验证：该 session_id 须在 slug 的共享 store 中可读（file-backed 已存在）。
        """
        slug = _require_slug(slug)
        self.resolve_ex(slug)
        store = self._store_for_slug(slug)
        s = store.get(session_id)
        if s is None:
            raise HostError(f"session 不存在于 store: {session_id}")
        self._sessions[session_id] = {"slug": slug}
        return session_id

    def _store_for(self, session_id: str):
        """该 session 所属 slug 的 file-backed SessionStore（session 按 session_id 隔离）。

        独立于 runtime（runtime rebuild 后 session 数据仍在），保证 confirm/reject 读到
        本 session 的真实 overlay。
        """
        slug = self.session_slug(session_id)
        return self._store_for_slug(slug)

    # ---------- Multi-turn orchestration ----------
    def respond(self, session_id: str, user_message: str) -> dict:
        if session_id not in self._sessions:
            raise HostError(f"未知 session: {session_id}")
        slug = self._sessions[session_id]["slug"]
        rt = self.get_runtime(slug)
        last_err = None
        for attempt in range(self.retry_transient + 1):
            try:
                out = rt.respond(user_message, session_id=session_id)
                break
            except ProviderError:
                raise
            except Exception as e:  # transient provider/timeout -> retry
                last_err = e
                if attempt >= self.retry_transient:
                    raise ProviderError(f"provider 失败，已重试 {attempt} 次: {last_err}") from last_err
        else:
            raise ProviderError(f"provider 失败: {last_err}")
        # session store save（与 LLM success 区分）
        store = self._store_for(session_id)
        try:
            store.save(rt.store.get(session_id))
        except Exception as e:
            # response 成功但 session save 失败 -> 明确错误，不伪造成功
            self._log("session_save_failure", {"session_id": session_id})
            raise SessionSaveError(f"session 保存失败: {e}") from e
        self._log("turn", {"session_id": session_id, "slug": slug})
        # R5: 出口抑制舞台/动作描写（只改 Host 返回给产品面的文本；runtime/session/persistence 不变）
        if isinstance(out.get("assistant_response"), str):
            out["assistant_response"] = _strip_stage_directions(out["assistant_response"])
        return out

    # ---------- Correction confirmation boundary ----------
    def _existing_proposals(self, slug: str) -> List[dict]:
        """已落盘 canonical 的 active correction → PROPOSAL_CONFIRMED 条目。

        proposal 状态的唯一事实源 = Instance canonical（instance_persistence write_back 的产物），
        不新建第二套 proposal 存储、不新增 session 字段。
        canonical 不可读时不抛：退化为"未见已确认"（即修复前行为，不会更差）。
        """
        try:
            pm = self._load_canonical(slug)
        except (ExNotFound, MalformedPersonaMemory):
            return []
        return [{"new_claim_id": c["id"], "status": "confirmed"}
                for c in (pm.get("corrections") or [])
                if c.get("status") == "active" and c.get("id")]

    def pending_proposals(self, session_id: str) -> List[dict]:
        """从 session overlay 取 pending correction proposals（correction_export 语义），供 Host 展示。

        已 confirm 并落盘 canonical 的 correction 不再返回（否则每轮重复弹出）。
        """
        if session_id not in self._sessions:
            raise HostError(f"未知 session: {session_id}")
        slug = self._sessions[session_id]["slug"]
        store = self._store_for(session_id)
        s = store.get(session_id)
        overlay = s.persona_overlay if s else []
        from correction_export import export_correction_proposals, PROPOSAL_PENDING
        r = export_correction_proposals(overlay,
                                        existing_proposals=self._existing_proposals(slug),
                                        source_session_id=session_id)
        return [p for p in r["proposals"] if p.get("status") == PROPOSAL_PENDING]

    def confirm_proposal(self, session_id: str, proposal_id: str) -> dict:
        """用户 confirm -> 调 persist_confirmed（唯一写回路径）。幂等：重复 confirm 不重复写。"""
        if session_id not in self._sessions:
            raise HostError(f"未知 session: {session_id}")
        slug = self._sessions[session_id]["slug"]
        pm_path = self.resolve_ex(slug)
        store = self._store_for(session_id)
        s = store.get(session_id)
        overlay = s.persona_overlay if s else []
        # 找匹配 proposal（by new_claim_id）
        from correction_export import export_correction_proposals, confirm_proposal as _confirm
        r = export_correction_proposals(overlay, source_session_id=session_id)
        target = next((p for p in r["proposals"] if p.get("proposal_id") == proposal_id
                       or p.get("new_claim_id") == proposal_id), None)
        if target is None:
            raise HostError(f"proposal 不存在: {proposal_id}")
        _confirm(target)  # pending -> confirmed
        from instance_persistence import write_back, get_instance_lock
        lock = get_instance_lock(pm_path)
        confirmed = [{"id": target.get("new_claim_id"), "corrected_value": target.get("corrected_value"),
                      "target_id": target.get("target_id"), "target_path": target.get("field"),
                      "user_statement": target.get("user_statement"), "created_at": target.get("created_at")}]
        try:
            res = write_back(pm_path, confirmed,
                             backup_dir=os.path.join(self.base_dir, slug, "versions"), lock=lock)
        except Exception as e:
            self._log("persist_failure", {"session_id": session_id, "proposal": proposal_id})
            raise PersistError(f"写回失败: {e}") from e
        # 使后续新 session 重新加载更新后的 canonical：标记该 slug 需 force_reload base。
        # （Stage 6.1 发现：不 reload 则新 session 复用 persist 前旧 base → 采用旧信息。
        #   file-backed store 独立于 runtime，故 rebuild 不清空 session 数据。）
        self._runtime_dirty.add(slug)
        self._log("correction_confirmed", {"session_id": session_id, "proposal": proposal_id})
        return res

    # ---------- G3 Memory Item Lifecycle ----------
    # 两个生命周期入口，数据源/API/op/语义四维分离：
    #   G3-3 new-fact proposal : session.pending_confirmations → create
    #   G3-1 pending memory item: canonical memory[].status    → decide
    # canonical 写入一律经 instance_persistence.write_back()（不在此处 json.dump）。

    def _lifecycle_bucket(self, content: str) -> Optional[str]:
        """new-fact 的分桶判定。fallback(shard_experiences) → None（不进入确认流程）。"""
        import persona_memory_builder as pmb
        if pmb._heuristic_bucket(content) == "shared_experiences":
            return None
        return pmb._heuristic_bucket(content)

    def pending_memory_proposals(self, session_id: str) -> List[dict]:
        """G3-3：session 内尚未裁决的 new-fact proposal。

        只返回 bucket 可明确确定的项；fallback(shared_experiences) 不返回，
        因此 CLI 不会为其提供"记住"入口（且 write_back 侧另有 fail-closed 闸门）。
        """
        if session_id not in self._sessions:
            raise HostError(f"未知 session: {session_id}")
        s = self._store_for(session_id).get(session_id)
        out = []
        for p in (s.pending_confirmations if s else []) or []:
            bucket = self._lifecycle_bucket(p.get("text") or "")
            if bucket is None:
                continue
            out.append({"proposal_id": p.get("proposal_id"), "text": p.get("text"),
                        "bucket": bucket, "created_at": p.get("created_at")})
        return out

    def pending_lifecycle_items(self, slug: str) -> List[dict]:
        """G3-1：canonical 中待用户裁决的 memory item（status=pending_confirmation）。"""
        slug = _require_slug(slug)
        pm = self._load_canonical(slug)
        out = []
        for bucket, items in (pm.get("memory") or {}).items():
            if not isinstance(items, list):
                continue
            for it in items:
                if it.get("status") == "pending_confirmation":
                    out.append({"item_id": it.get("id"), "bucket": bucket,
                                "content": it.get("content"),
                                "conflicts_with": it.get("conflicts_with") or []})
        return out

    def _write_lifecycle(self, slug: str, ops: List[dict]) -> dict:
        """唯一落盘路径：instance_persistence.write_back(lifecycle_ops=...)。"""
        from instance_persistence import write_back, get_instance_lock
        pm_path = self.resolve_ex(slug)
        lock = get_instance_lock(pm_path)
        try:
            res = write_back(pm_path, [], lifecycle_ops=ops, lock=lock,
                             backup_dir=os.path.join(self.base_dir, slug, "versions"))
        except Exception as e:
            self._log("lifecycle_persist_failure", {"slug": slug})
            raise PersistError(f"写回失败: {e}") from e
        self._runtime_dirty.add(slug)   # 下次 get_runtime 从更新后的 canonical 重建
        return res

    def decide_memory_proposal(self, session_id: str, proposal_id: str, approve: bool) -> dict:
        """G3-3 裁决：approve → create；reject → 不写 canonical（canonical 零变化）。"""
        if session_id not in self._sessions:
            raise HostError(f"未知 session: {session_id}")
        slug = self._sessions[session_id]["slug"]
        s = self._store_for(session_id).get(session_id)
        target = next((p for p in ((s.pending_confirmations if s else []) or [])
                       if p.get("proposal_id") == proposal_id), None)
        if target is None:
            raise HostError(f"proposal 不存在: {proposal_id}")
        ops = []
        if approve:
            ops = [{"kind": "create", "content": target.get("text")}]
        res = self._write_lifecycle(slug, ops)
        self._log("memory_proposal_decided",
                  {"session_id": session_id, "proposal_id": proposal_id, "approve": bool(approve)})
        return res

    def decide_lifecycle_item(self, slug: str, item_id: str, approve: bool) -> dict:
        """G3-1 裁决：仅接受 pending_confirmation（其余状态由 frozen 侧 status_mismatch 挡下）。"""
        slug = _require_slug(slug)
        bucket = self._bucket_of_item(slug, item_id)
        if bucket is None:
            raise HostError(f"memory item 不存在: {item_id}")
        ops = [{"kind": "decide", "bucket": bucket, "item_id": item_id,
                "expect_status": "pending_confirmation", "approve": bool(approve)}]
        res = self._write_lifecycle(slug, ops)
        self._log("lifecycle_item_decided", {"slug": slug, "item_id": item_id, "approve": bool(approve)})
        return res

    def revive_rejected_item(self, slug: str, item_id: str) -> dict:
        """G3-1 复活：**唯一**能把 rejected 变回 active 的入口（独立、显式、不可被批量 approve 误触）。"""
        slug = _require_slug(slug)
        bucket = self._bucket_of_item(slug, item_id)
        if bucket is None:
            raise HostError(f"memory item 不存在: {item_id}")
        ops = [{"kind": "decide", "bucket": bucket, "item_id": item_id,
                "expect_status": "rejected", "approve": True}]
        res = self._write_lifecycle(slug, ops)
        self._log("lifecycle_item_revived", {"slug": slug, "item_id": item_id})
        return res

    def _bucket_of_item(self, slug: str, item_id: str) -> Optional[str]:
        pm = self._load_canonical(slug)
        for bucket, items in (pm.get("memory") or {}).items():
            if not isinstance(items, list):
                continue
            if any(it.get("id") == item_id for it in items):
                return bucket
        return None

    # ---------- telemetry placeholder (host event interface) ----------
    def _log(self, event: str, data: dict):
        self.event_log.append({"event": event, "data": data})
