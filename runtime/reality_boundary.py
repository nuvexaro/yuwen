#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reality Boundary（P0 安全边界，deterministic pre-check + flags）。

区分用户消息类别 + 检测时间/地点/事件冲突。产出的 reality_flags 供
persona_constraints / post-filter 使用。原则：宁可不确定，不编造。
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, List, Optional

# 当前年份（供测试注入 now 而非真实时钟）
_CURRENT_YEAR = datetime.now().year


_REFUTE_FIRST = re.compile(
    r"^(不对|不是|才不是|并不是|没有的事|没这回事|别这么说|你听我说|我是说|你搞错|你说错|别乱说)"
)
_REFUTE_MID = re.compile(r"(才不是|并不是|又没有|又不是|其实(是|不是|呢|吧)|没这回事|没有的事|别乱说|搞错了吧)")
# 定向“你记错/你说错”（不匹配“你是不是记错了？”里作为问句一部分的裸“记错了”）
_YOU_MISREMEMBER = re.compile(r"(你|您)记错|(你|您)说错|(你|您)记错了")


def _looks_like_refutation(text: str) -> bool:
    """是否“反驳/纠正”句（correction）。

    Stage 5.9-A4 修正：否定词“不是”必须是句首/反驳结构才算纠正，
    避免把“你是不是记错了？”“我们去年是不是去过上海？”这类含“是不是”的
    问句误判成 correction（应归 question）。
    """
    t = text.strip()
    if not t:
        return False
    if _REFUTE_FIRST.search(t):
        return True
    if _REFUTE_MID.search(t):
        return True
    if _YOU_MISREMEMBER.search(t):
        return True
    # “不是 X，而是/是 Y”的反驳结构（非“是不是”）
    if "是不是" not in t and re.search(r"不是[^？?。！!，,]{1,10}[，,]?\s*(而是|就是|是)", t):
        return True
    return False


def classify_user_message(text: str) -> str:
    """返回 correction / guess / question / assertion 之一。deterministic 启发式。

    Stage 5.9-A1 (F4)：顺序为 correction → guess → question → assertion。
      - guess marker（可能/大概/我猜…）先于 ? 判定，避免“可能…吧？”被 ? 短路成 question；
      - “是不是/是不是…？”不因含“不是”子串被误判为 correction（见 _looks_like_refutation）。
    """
    t = text.strip()
    if not t:
        return "assertion"
    # correction 反驳/纠正句式（宽松的“不是”子串不再吞掉“是不是”问句）
    if _looks_like_refutation(t):
        return "correction"
    # guess marker（优先于 ? 结尾；guess 可带 ?）
    if re.search(r"(可能|大概|也许|应该是|我猜|我想是|估计)", t):
        return "guess"
    # question
    if t.endswith("？") or t.endswith("?") or re.search(r"^(还记得|你还记得|是不是|有没有|我们.*吗|.*?去没去过)", t):
        return "question"
    return "assertion"


_YEAR_RE = re.compile(r"(20\d{2}|19\d{2})年?")


def extract_year(text: str) -> Optional[str]:
    m = _YEAR_RE.search(text)
    return m.group(1) if m else None


# ---- Stage 5.9-A2 (F1)：五态 Reality Boundary ----
# 原则：absence of evidence ≠ evidence of absence。
# 不能把 "retrieval 空" 当成 "证据不存在"；只有枚举 active memory 证明真空才算 unsupported。

# 具体"过去/共享事件"实体回指标记：命中才可能进 unsupported/insufficient 判定。
# 寒暄 / 情绪 / 当前时态非事实句不含这些 → ordinary，绝不误伤。
_ENTITY_REF = re.compile(
    r"(上海|北京|外滩|广州|深圳|杭州|成都|那家店|那个谁|那次|那次去|去年|前年|"
    r"当初|以前|还记得|怎么认识|认识|一起去过|去没去过|是不是去过|去过|吃日料|"
    r"20\d{2}年|[一二三四五六七八九十]\d*年前|那年)"
)
# 相识 / 共同经历意图（F6 预留，也用于 F1 的实体判定）
_ACQUAINT_REF = re.compile(r"(怎么认识|当初|还记得我吗|我们.*认识)")


def _active_memory_count(persona_memory: dict) -> int:
    """枚举 active persona memory 项总数（唯一可靠的“空/非空”判据）。"""
    total = 0
    for bucket in (persona_memory.get("memory") or {}).values():
        for m in bucket or []:
            if m.get("status") == "superseded":
                continue
            total += 1
    return total


def _subject_related(user_message: str, memory_items: List[dict]) -> bool:
    """retrieval score≥0.2 不算支撑：校验召回项与被质疑主体是否实质相关。

    CJK 检索按单字切分，故“外滩”= {外,滩}(2 字)。支撑判据：
      - overlap 命中 ≥2 个单字（外+滩 = 真实地名），或
      - 命中 ≥1 个多字节 ascii/词 token（如 2022）。
    仅 1 个单字命中（如“们”导致 0.383 假阳性召回）不算相关 → 不当作 supported。
    倾向“宽支撑、窄拒绝”，避免把真实相关记忆误判为 insufficient_evidence 而过度 hedge。
    """
    from memory_retrieval import _terms as mr_terms
    ut = mr_terms(user_message)
    for it in memory_items:
        m = it.get("memory", it)
        mt = mr_terms(m.get("content", ""))
        hit = ut & mt
        if any(len(t) > 1 for t in hit):
            return True
        if len(hit) >= 2:
            return True
    return False


def assess_support(persona_memory: dict, user_message: str, *, retrieved_items: List[dict] = None,
                   now: Optional[datetime] = None, flags: Optional[dict] = None) -> dict:
    """五态 Reality Boundary（在 retrieval 之后调用）。

    返回合并进 reality_flags 的增量字段：
      boundary_state : supported | conflicting | insufficient_evidence | unsupported_claim | ordinary
      boundary_active: bool（conflicting / insufficient_evidence / unsupported_claim → True）
      boundary_guard : 该 state 应注入 system 的护栏文案（空串则不注入）
      contested      : 被质疑的实体/年份描述（供 post-filter 结构化判定用）

    判定优先级（deterministic）：
      1. 无具体"过去/共享"实体回指 → ordinary（寒暄/情绪/当前事实句不误伤）
      2. 现有 check_reality 已冲突 → conflicting
      3. 枚举 active memory 真空 → unsupported_claim
      4. 召回且主体相关 → supported
      5. 其余（memory 非空但召回为空/不相关）→ insufficient_evidence（不否认、不确认）
    """
    flags = dict(flags or {})
    cat = flags.get("user_category") or classify_user_message(user_message)
    # 1) correction 不走 boundary（由 F5/correction 路径处理）
    if cat == "correction":
        return {"boundary_state": "ordinary", "boundary_active": False,
                "boundary_guard": "", "contested": None}
    has_ref = bool(_ENTITY_REF.search(user_message))
    if not has_ref:
        return {"boundary_state": "ordinary", "boundary_active": False,
                "boundary_guard": "", "contested": None}
    # 2) 现有时间冲突（含已知年份 memory + 用户相对/绝对年更晚）
    #    注：conflicting 的护栏由现有 reality_conflict → persona_constraints 的
    #    “[现实边界提醒]”渲染，此处不再重复注入（boundary_guard 留空避免双份）。
    if flags.get("reality_conflict"):
        contested = flags.get("note", "")
        return {"boundary_state": "conflicting", "boundary_active": True,
                "boundary_guard": "", "contested": contested}
    # 3) 枚举真空 → unsupported
    if _active_memory_count(persona_memory) == 0:
        contested = user_message
        guard = ("（现实边界）我不记得我们有过这段共同经历；"
                 "可以把 TA 说的当作 TA 的想法，但别把它当成确定发生过的事。"
                 "如果真没印象，可以说不记得 / 不太确定 / 没印象。")
        return {"boundary_state": "unsupported_claim", "boundary_active": True,
                "boundary_guard": guard, "contested": contested}
    # 4) 召回且主体相关 → supported
    items = retrieved_items or []
    if items and _subject_related(user_message, items):
        return {"boundary_state": "supported", "boundary_active": False,
                "boundary_guard": "", "contested": None}
    # 5) memory 非空但召回缺失/不相关 → insufficient_evidence
    guard = ("（现实边界）我不太确定你指的是哪次 / 哪年；"
             "别把 TA 说的话直接当成确定事实，也别断言它没发生过。"
             "不确定就说不确定。")
    return {"boundary_state": "insufficient_evidence", "boundary_active": True,
            "boundary_guard": guard, "contested": user_message}


def check_reality(persona_memory: dict, user_message: str,
                  *, now: Optional[datetime] = None) -> Dict:
    """返回 reality_flags：检测 去年/今年 与已知事件时间冲突、旧事件误当最近等。

    规则 deterministic：把 user_message 中的相对时间词(去年/今年/上个月…)与
    memory 里的绝对年份对撞，若 conflict 置 flags.reality_conflict + 附解释。
    """
    year = (now or datetime.now()).year
    flags = {
        "reality_conflict": False,
        "conflict_kind": None,
        "note": "",
        "user_category": classify_user_message(user_message),
        "known_year_from_memory": None,
        "user_year_ref": None,
    }
    # 收集 memory 中 active 事件的年份（timeline/preferences/core_facts 的 content 里显式年份）
    known_years = []
    for bucket in persona_memory.get("memory", {}).values():
        for m in bucket:
            if m.get("status") == "superseded":
                continue
            y = extract_year(m.get("content", ""))
            if y:
                known_years.append((y, m.get("content", "")[:20]))
    # 相对词
    rel = None
    if "去年" in user_message:
        rel = str(year - 1)
    elif "前年" in user_message:
        rel = str(year - 2)
    elif "今年" in user_message:
        rel = str(year)
    elif "上个月" in user_message:
        rel = str(year)
    abs_user = extract_year(user_message)
    user_ref = abs_user or rel
    flags["user_year_ref"] = user_ref

    # 冲突：user 说去年/具体年，但 active memory 只有更早年份且无该年事件
    if user_ref:
        known_years_dedup = sorted({y for y, _ in known_years})
        if known_years_dedup:
            latest_known = known_years_dedup[-1]
            flags["known_year_from_memory"] = latest_known
            if rel and latest_known < rel:
                # user 把旧事件当最近，或 memory 无该相对年事件
                flags["reality_conflict"] = True
                flags["conflict_kind"] = "relative_time_mismatch"
                flags["note"] = (f"记忆中最晚事件在 {latest_known} 年，用户说『{rel} 年』，"
                                 "倾向已知记忆，不要迎合改口；不确定就说不确定。")
            elif abs_user and abs_user not in known_years_dedup and known_years_dedup:
                # 具体年但 memory 无此年事件
                flags["reality_conflict"] = True
                flags["conflict_kind"] = "unknown_year_asserted"
                flags["note"] = f"记忆无 {abs_user} 年事件；不把用户断言当作事实。"
    return flags
