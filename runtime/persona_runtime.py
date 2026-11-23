#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Persona Runtime orchestrator（Stage 5.7 MVP）。

User → 检索 → Context Assembly → Persona 约束 → LLM Gateway → Reality post-filter
     → Response → Session update → optional Memory proposal

Runtime 只读冻结 persona_memory v1.2；不建立第二套 Persona/Memory 数据体系。
LLM 永不能直接改 persona/memory；新事实只进 proposal（异步，经 5.2–5.5 确认回流）。
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from typing import Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(os.path.dirname(HERE), "tools")
for p in (HERE, TOOLS):
    if p not in sys.path:
        sys.path.insert(0, p)

from llm_gateway import LLMGateway, ChatMessage, GatewayError  # noqa: E402
from session_store import SessionStore, Session  # noqa: E402
import memory_retrieval as mr  # noqa: E402
import reality_boundary as rb_  # noqa: E402
import context_assembly as ca  # noqa: E402
import persona_constraints as pc  # noqa: E402
import correction_runtime as cr  # noqa: E402
import memory_proposal as mp  # noqa: E402


class RuntimeError(Exception):
    pass


def _validate_persona_memory(pm: dict) -> List[str]:
    # 轻量结构校验：非空核心
    if not isinstance(pm, dict) or "persona" not in pm or "memory" not in pm:
        return ["persona_memory 缺 persona/memory"]
    if "name_or_alias" not in pm.get("persona", {}).get("identity", {}):
        # name 经 claim 化（5.5 产物）——identity.name_or_alias 是 claim dict
        na = pm.get("persona", {}).get("identity", {}).get("name_or_alias")
        if not (isinstance(na, dict) and "value" in na):
            return ["identity.name_or_alias 缺失/非法"]
    return []


def _persona_name(pm: dict) -> str:
    na = pm.get("persona", {}).get("identity", {}).get("name_or_alias")
    if isinstance(na, dict):
        return na.get("value") or "ta"
    return "ta"


class PersonaRuntime:
    def __init__(self, *, persona_memory: dict, gateway: Optional[LLMGateway] = None,
                 session_store: Optional[SessionStore] = None,
                 context_budget: int = 2000, now: Optional[datetime] = None):
        errs = _validate_persona_memory(persona_memory)
        if errs:
            raise RuntimeError("persona_memory 非法: " + "; ".join(errs))
        self.persona_memory = persona_memory
        self.gateway = gateway or LLMGateway()
        self.store = session_store or SessionStore()
        self.context_budget = context_budget
        self.now = now

    def _name(self):
        return _persona_name(self.persona_memory)

    def respond(self, user_message: str, *, session_id: Optional[str] = None) -> Dict:
        """一次对话轮。返回 output contract dict。"""
        session = self.store.get_or_create(session_id, persona_id="default")
        name = self._name()

        # 0) 分类 + reality pre-check
        category = rb_.classify_user_message(user_message)
        rflags = rb_.check_reality(self.persona_memory, user_message, now=self.now)

        # correction 检测（优先）
        correction_result = None
        is_correction_turn = False
        if category == "correction":
            is_correction_turn = True
            candidate = CorrectionCandidateInput(user_message)
            correction_result = self._handle_correction(session, user_message)

        # 1) retrieval
        # Stage 5.9-B (F5-d D3)：非 correction 普通轮用 effective_memory_view 投影
        #   （memory-domain correction 可被检索/support 看到）。correction 当前轮禁 self-project
        #   → 仍用 frozen persona_memory，让本条 correction 不参与自身 retrieval/support/boundary。
        #   同一条 correction 在 system overlay 与 retrieval projection 用同一 new_claim_id → 单一事实源。
        if is_correction_turn:
            retrieval_pm = self.persona_memory          # 禁 self-projection
        else:
            retrieval_pm = cr.effective_memory_view(self.persona_memory, session.persona_overlay)
        retrieved = mr.retrieve(retrieval_pm, session.to_dict(), user_message,
                                k=5, now=self.now)

        # 1.5) Stage 5.9-A2/A3 (F1+F2)：五态 boundary 判定（correction 轮 assess_support 返回 ordinary）
        support = rb_.assess_support(retrieval_pm, user_message,
                                     retrieved_items=retrieved.get("items", []),
                                     now=self.now, flags=rflags)
        rflags.update(support)

        # 2) context assembly
        recent = session.recent(8)
        try:
            ctx = ca.assemble(self.persona_memory, name, user_message,
                              retrieved=retrieved, session_recent=recent,
                              reality_flags=rflags, budget=self.context_budget,
                              session_overlay=session.persona_overlay)
        except ca.BudgetExceededError:
            return {"assistant_response": "……（这条我接不住，换个说法？）",
                    "used": {"persona_claims": [], "memory_items": [],
                             "session_context_used": False},
                    "reality_flags": rflags, "session_update": session.to_dict(),
                    "memory_proposals": [], "error": "context_budget_exceeded"}

        # 3) persona constraints 已在 ctx.system_text（含 guardrail + L0..L4 + memory）
        # 4) LLM gateway
        system_msg = ChatMessage("system", ctx["system_text"])
        user_msg = ChatMessage("user", ctx["user_text"])
        try:
            raw = self.gateway.chat([system_msg, user_msg], max_tokens=256)
        except GatewayError:
            # deterministic fallback：明确属 runtime fallback，不伪装 persona 记忆/台词。
            # （Frozen reopen, failure observability）暴露 machine-readable error，使 Host
            #  能区分真实 LLM 成功与 gateway fallback；不改 fallback 文本/persona 语义。
            raw = "……（先不说这个了。）"  # runtime fallback（中性、不编造）
            gateway_fallback = True
        else:
            gateway_fallback = False

        # 5) boundary post-filter（Stage 5.9-A2/A3/A4：F1 五态 + F2 门控 + F3 确认检测）
        #    boundary_active = conflicting OR insufficient_evidence OR unsupported_claim。
        #    不拦截：ordinary / supported / correction 轮；以及模型已自现不确定（hedged）。
        final = raw
        if rflags.get("boundary_active") and _detect_confirmation(raw, rflags):
            final = "……我不太确定是不是你说的那次/那年。你具体说说？"
        # 5b) 事后检查：记录里没有这件事时，回复若编出大量查不到的具体内容 → 换成中性回应
        postcheck = None
        if rflags.get("boundary_state") in ("insufficient_evidence", "unsupported_claim"):
            if _untraceable_narrative(final, _source_text(self.persona_memory, retrieved, user_message)):
                final = "……具体的事我记不清了。你愿意的话，跟我说说？"
                postcheck = "untraceable_narrative"

        # 6) session update
        session.add_turn("user", user_message)
        session.add_turn("assistant", final)
        if rflags.get("reality_conflict"):
            session.corrections_made.append({"kind": "reality_conflict", "at": datetime.now().isoformat()})
        # topic
        session.last_topics = _topics(user_message, session.last_topics)

        # 7) memory proposal（新事实）
        proposal = mp.build_proposal(user_message, source_session=session.session_id, category=category)
        mp.record_proposal(session, proposal)

        # 持久化 session（file-backed 时）
        self.store.save(session)

        used = ctx["used"]
        used["retrieved_candidates"] = retrieved.get("used_ids", [])
        ret = {
            "assistant_response": final,
            "used": used,
            "reality_flags": rflags,
            "session_update": session.to_dict(),
            "memory_proposals": [proposal] if proposal else [],
            "correction_result": correction_result,
        }
        # Failure observability（authorized minimal reopen）：gateway fallback 时暴露 error 字段，
        # 对齐既有 context_budget_exceeded 的 error 先例；success 路径无此字段。
        if gateway_fallback:
            ret["error"] = "gateway_fallback"
        if postcheck:
            ret["postcheck"] = postcheck
        return ret

    def _handle_correction(self, session: Session, user_message: str) -> Dict:
        cv = cr.extract_corrected_value(user_message)
        result = {"detected": True, "applied_overlay": False, "new_claim_id": None,
                  "old_claim_id": None, "note": "", "target_domain": None}
        if cv is None:
            result["note"] = "未提取到 corrected value；记为用户反馈，不自动 overlay"
            session.corrections_made.append({"kind": "correction", "note": result["note"]})
            return result
        # Stage 5.9-B (F5-b): 确定性 target resolution（不再取 speech_style 第一个 claim）
        tgt = cr.resolve_correction_target(self.persona_memory, user_message)
        if not tgt.get("ok") or tgt.get("domain") == "unresolved":
            # 无法确定域/目标：不硬 overlay，绝不乱选已有 claim。记录 + 走 proposal。
            result.update({"note": f"correction target unresolved: {tgt.get('reason')}",
                           "target_domain": "unresolved"})
            session.corrections_made.append({"kind": "correction",
                                             "user_statement": user_message,
                                             "target_resolution": "unresolved",
                                             "reason": tgt.get("reason"),
                                             "at": datetime.now().isoformat()})
            return result
        # 生成 overlay 确定性 id：persona 用 claim_id(field,new)，memory 用 memory_item_id(bucket,new)
        domain = tgt["domain"]
        new_id = None
        if domain == "persona":
            field = tgt.get("field") or "persona.speech_style"
            new_id = (cr._pm_claim_id(field, cv) if cr._pm_claim_id else None)
        else:  # memory / relationship_memory / shared_memory
            bucket = (tgt.get("field") or "memory.core_facts").replace("memory.", "")
            new_id = (cr._pm_memory_item_id(bucket, cv) if cr._pm_memory_item_id else None)
        overlay_entry = {
            "target_domain": domain,
            "target_kind": tgt.get("target_kind"),
            "target_id": tgt.get("target_id"),
            "old_value": None,
            "corrected_value": cv,
            "new_claim_id": new_id,
            "field": tgt.get("field"),
            "source_turn": user_message,
            "at": datetime.now().isoformat(),
        }
        session.persona_overlay.append(overlay_entry)
        result.update({
            "applied_overlay": True,
            "new_claim_id": new_id,
            "old_claim_id": tgt.get("target_id"),
            "target_domain": domain,
            "field": tgt.get("field"),
        })
        session.corrections_made.append({"kind": "correction", "target_domain": domain,
                                         "user_statement": user_message,
                                         "new_claim_id": new_id,
                                         "old_claim_id": tgt.get("target_id"),
                                         "at": datetime.now().isoformat()})
        return result


_STOP_BIGRAMS = {
    "我们", "你们", "他们", "什么", "怎么", "这个", "那个", "时候", "现在", "觉得",
    "知道", "可以", "就是", "但是", "因为", "所以", "已经", "还是", "其实", "真的",
    "有点", "一下", "一个", "这样", "那样", "不是", "没有", "不能", "应该", "如果",
    "然后", "而且", "只是", "这么", "那么", "心里", "感觉", "事情", "地方", "东西",
    "起来", "出来", "过来", "下来", "可能", "大概", "也许", "好像", "记得", "不清",
    "不记", "确定", "印象", "告诉", "说说", "聊聊", "要不", "愿意", "情况", "具体",
}


def _content_bigrams(text: str) -> set:
    """抽 2 字内容词（去标点、去停用/虚词），用于判断"回复里有没有新东西"。"""
    import re
    segs = re.sub(r"[^\u4e00-\u9fff]+", " ", text or "").split()
    out = set()
    for seg in segs:
        for i in range(len(seg) - 1):
            g = seg[i:i + 2]
            if g in _STOP_BIGRAMS:
                continue
            if any(ch in "的了是在有和就都也我你他她它们这那么什怎" for ch in g):
                continue
            out.add(g)
    return out


def _untraceable_narrative(reply: str, sources_text: str) -> bool:
    """回复里的具体内容能否在「人格 + 命中记忆 + 用户原话」里找到。

    只在 boundary_active（记录里没有这件事）时调用：此时任何**大段新内容**都不可信——
    包括"先说记不清、再补细节"的写法。规则刻意与具体词表无关：
    2 字内容词里，超过 60% 在来源中找不到、且新词 ≥6 个 → 判为不可追溯叙事。
    """
    if not isinstance(reply, str) or len(reply) < 30:
        return False
    grams = _content_bigrams(reply)
    if len(grams) < 6:
        return False
    novel = [g for g in grams if g not in sources_text]
    return len(novel) >= 6 and len(novel) / len(grams) >= 0.6


def _source_text(persona_memory: dict, retrieved: dict, user_message: str) -> str:
    import json
    parts = [user_message or "", json.dumps(persona_memory, ensure_ascii=False)]
    for it in (retrieved or {}).get("items", []):
        parts.append((it.get("memory") or {}).get("content") or "")
    return "\n".join(parts)


def _detect_confirmation(reply: str, flags: dict) -> bool:
    """Stage 5.9-A4 (F3)：deterministic confirmation detection（只在 boundary_active 轮调用）。

    输入：assistant reply + boundary flags（含 contested claim 描述）。
    原则：不做“出现嗯=确认”。confirmation 必须与 contested claim 存在明确关系。
    先排除 hedged（模型已不确定 → 不重复替换）→ 再判“明确确认/重述被质疑事实”。

    应拦截（示例）：嗯 去过 / 对，去年去过外滩 / 去过啊 / 嗯 就是去年去的 / 对，是去过 / 嗯 是
    不拦截：可能吧 / 好像去过 / 我不太记得了 / 忘了 / 不太确定 /
            嗯，怎么突然问这个（反问未确认）/ 嗯，知道了（未重述被质疑事实）/
            记得（无对象，不构成对 contested 的具体确认）
    """
    import re
    if not isinstance(reply, str) or not reply:
        return False
    t = reply.strip()
    # 1) hedged（含模糊/不确定）→ 已不确定，放行
    if re.search(r"(不确定|记不清|不记得|忘了|没印象|没去过|不知道|可能|大概|也许|好像|应该)", t):
        return False
    # 2) 显式确认词 +（后续重述 OR 无对象纯确认，仅当是 yes/no 问句）
    #    contested 取自 user 原句，用于判断 reply 是否“重述被质疑事实”。
    contested = (flags.get("contested") or "").strip()
    # 3) 判定
    if re.search(r"(对[，,。!！]?|是的|没错|当然|就是)", t):
        # “对/是的/没错”开头=对用户断言的确认；其后是否重述皆算（yes/no 问句语境）
        return True
    # 裸“嗯/哦/啊” + 后续重述被质疑地点/时间动词
    if re.match(r"^(嗯|哦|啊|嗯嗯)[，,。!！]?\s*", t):
        rest = re.sub(r"^(嗯|哦|啊|嗯嗯)[，,。!！]?\s*", "", t)
        if re.search(r"(去过|去了|有去|在过|去过吧|去过啊|是的|就是|去过那边)", rest):
            return True
        # “嗯 是”“嗯 去过了”这类极短肯定也拦（yes/no contested 语境）
        if re.search(r"^(是|去过|去了|去过吧|对)$", rest):
            return True
        # 若 contest 里含明确地点，rest 重述该地点也算（如“嗯 去年去过外滩”→外滩在 contested）
        if contested and _restates_contested(rest, contested):
            return True
        return False  # “嗯 知道了/嗯 怎么突然问这个/嗯 记得”不拦
    # 无“嗯”前缀：整句为对被质疑事件的确认重述（如“去过啊”“去年去过外滩”）
    if re.search(r"(去过啊|去过了|去过那边|去过外滩|去年去过|就是去年|当然去过)", t):
        return True
    if re.search(r"^(去过|去了|去过了|是去过|去过啊)[，,。!！]?$", t):
        return True
    if contested and _restates_contested(t, contested):
        # “去年去过外滩”等整句重述 contested 中的地点/年
        return bool(re.search(r"(去过|去了|有去|在过)", t))
    return False


def _restates_contested(reply: str, contested: str) -> bool:
    """reply 是否重述了 contested(user 原句) 里的地点/关键实体。确定性：抽两串的共有双字 token。"""
    import re
    places = re.findall(r"[一-鿿]{2,4}(?=吧|吗|呢|的|了|去过|去|那|？|。|\s|$)", contested)
    if not places:
        return False
    for p in places:
        # 双字地点（如“外滩/上海”）若整串出现在 reply → 重述
        if len(p) >= 2 and p in reply:
            return True
    # 兜底：年/相对时间词被重述
    if any(w in reply for w in ("去年", "前年")) and "去过" in reply:
        return True
    return False


def _topics(msg: str, prev: List[str]) -> List[str]:
    # 简易：取前 2 个非停用字 as 主题（确定性）
    import re
    stop = set("的了是在有和我你她他也就会把被让跟对从去来说到过那就吧吗呢啊哈嗯 的吗")
    chars = [c for c in msg if c not in stop and re.match(r"[一-鿿a-zA-Z]", c)]
    t = "".join(chars[:6])
    if t:
        prev = [t] + [x for x in prev if x != t]
    return prev[:5]


class CorrectionCandidateInput:
    def __init__(self, text):
        self.text = text
