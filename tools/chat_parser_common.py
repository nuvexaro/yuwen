#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""聊天记录解析共享内核

供 wechat_parser.py / qq_parser.py 复用。职责：编码探测、确定性 message id、
时间规范化、participants 初判/确认覆盖解析、ChatImport 组装、统一异常。

原则（与 message.schema.json v1.1 对齐）：
- 不猜：不猜 sender 角色、不猜时间、不猜媒体、不猜引用、不猜撤回。
- 保真：原始 sender 名、sent_at_raw、body（含换行/错别字/emoji/占位符）逐字保留。
- 诚实：解析不了就显式报错（UnsupportedFormatError / ParseError），绝不静默当 plaintext。
- 隐私：日志只打文件 basename，不打全路径；不打消息正文。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime
from typing import Dict, List, Optional

SCHEMA_VERSION = "1.2"

# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------
class ParserError(Exception):
    """解析失败基类。携带 文件/格式/位置/原因，便于可诊断错误。"""

    def __init__(self, reason: str, *, filename: str = "", fmt: str = "",
                 line: Optional[int] = None, region: str = ""):
        self.reason = reason
        self.filename = filename
        self.fmt = fmt
        self.line = line
        self.region = region
        head = f"[{fmt}] " if fmt else ""
        loc = ""
        if filename:
            loc = filename
        if line is not None:
            loc += f" at line {line}"
        if region:
            loc += f" region={region}"
        super().__init__(f"{head}{loc}: {reason}".strip(" "))

    def summary(self) -> str:
        return str(self)


class UnsupportedFormatError(ParserError):
    """格式明确不支持。禁止静默降级解析。"""


class EncodingError(ParserError):
    """无法可靠解码文件编码。"""


# ---------------------------------------------------------------------------
# 日志：只输出 basename 与计数，不输出正文/全路径
# ---------------------------------------------------------------------------
def log(msg: str) -> None:
    sys.stderr.write(msg + "\n")


def basename_only(path: str) -> str:
    return os.path.basename(path)


# ---------------------------------------------------------------------------
# 编码探测
# ---------------------------------------------------------------------------
def read_text_file(file_path: str) -> str:
    """读取文件文本。按 BOM / 严格 utf-8 / gb18030 顺序尝试，绝不 errors=ignore。

    中文聊天导出常见 utf-8(-BOM) 或 GBK/GB18030。二进制（含 NUL）或解码全失败抛 EncodingError。
    """
    with open(file_path, "rb") as f:
        raw = f.read()

    if not raw:
        return ""

    if b"\x00" in raw[:4096]:
        raise EncodingError("文件含 NUL 字节，疑似二进制/加密数据库，不是文本导出",
                            filename=basename_only(file_path))

    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig")
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        try:
            return raw.decode("utf-16")
        except UnicodeDecodeError as e:
            raise EncodingError(f"utf-16 解码失败: {e}", filename=basename_only(file_path))

    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise EncodingError("无法以 utf-8 或 gb18030 解码，请确认为纯文本导出",
                        filename=basename_only(file_path))


# ---------------------------------------------------------------------------
# 名字 / 匹配
# ---------------------------------------------------------------------------
def normalize_name(raw: str) -> str:
    """匹配用归一化：去除全部空白（含内部），保留大小写与字符本体。"""
    return re.sub(r"\s+", "", raw or "")


def slugify(text: str) -> str:
    """从文件名/任意字符串生成 source_ref 缺省值。保留字母数字与中文等，其余转 _。"""
    out = re.sub(r"[^\w一-鿿぀-ヿ가-힯-]+", "_", text)
    out = out.strip("_")
    return out[:80] or "import"


# ---------------------------------------------------------------------------
# 确定性 message id 与 content_fingerprint（职责分离）
#
# 两个概念不再混用：
#   * message id     —— 同一 ChatImport 内的唯一身份。保证导入内绝不出现两条
#                       不同消息拥有同一个 id；稳定（同文件重解析结果一致）、
#                       可复现（确定性，不用随机 UUID）。sequence 参与计算，
#                       用于打破「同人同秒同正文」的碰撞。
#   * content_fingerprint —— 跨 source_ref 的重叠导入中判断「可能是同一条消息」
#                       的候选指纹。不含 sequence：相同原始消息无论落在文件
#                       第几条，指纹都一致。它只提供候选集，最终去重还需结合
#                       上下文（sender/sent_at/相邻消息/source_ref）确认，
#                       不单独作为唯一判定。
# ---------------------------------------------------------------------------
_ID_FIELD_SEP = "\x1f"


def compute_message_id(platform: str, sender_key: str, sent_at_raw: str,
                       body: str, content_type: Optional[str], sequence: int) -> str:
    """导入内唯一、稳定、可复现的消息身份。

    canonical = platform \x1f sender_key \x1f sent_at_raw \x1f sequence
                \x1f body \x1f content_type
    sequence 在导入内唯一 ⇒ 同人同秒同正文的连发消息得到不同 id（无碰撞）。
    同文件重复解析 → 相同的 sequence → 相同 id（可复现）。
    """
    canon = _ID_FIELD_SEP.join([
        platform,
        sender_key or "",
        sent_at_raw or "",
        str(int(sequence)),
        body if body is not None else "",
        content_type or "",
    ])
    digest = hashlib.sha1(canon.encode("utf-8", "surrogatepass")).hexdigest()
    return "m_" + digest[:16]


def compute_content_fingerprint(platform: str, sender_key: str, sent_at_raw: str,
                                body: str, content_type: Optional[str]) -> str:
    """跨导入去重候选指纹。不掺 sequence：同一条原始消息，指纹恒定。

    canonical = platform \x1f sender_key \x1f sent_at_raw \x1f body \x1f content_type
    两份重叠导出中同一条消息 → 相同指纹 → 可作为「候选重复」信号；
    但两条同秒同正文的真消息也会共享指纹 —— 因此指纹只负责缩小候选，
    最终去重必须结合 sequence 邻近性 / 上下文 确认，而不是凭指纹单独判重。
    """
    canon = _ID_FIELD_SEP.join([
        platform,
        sender_key or "",
        sent_at_raw or "",
        body if body is not None else "",
        content_type or "",
    ])
    digest = hashlib.sha1(canon.encode("utf-8", "surrogatepass")).hexdigest()
    return "f_" + digest[:16]


def assert_unique_ids(messages: List[dict], filename: str = "") -> None:
    """防御性校验：同一 ChatImport 内 id 必须两两不同。违反即 ParserError。"""
    seen = set()
    for i, m in enumerate(messages):
        mid = m.get("id")
        if mid in seen:
            raise ParserError(f"消息 #{i} 的 id 重复: {mid}（导入内唯一性被破坏）",
                              filename=filename, region="message_ids")
        seen.add(mid)


# ---------------------------------------------------------------------------
# 时间规范化
# ---------------------------------------------------------------------------
_TS_FULL = re.compile(
    r"^(\d{4})-(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{2})(?::(\d{2}))?$"
)


def normalize_timestamp(raw: str) -> Optional[str]:
    """把完整日期时间规范化为 ISO 字符串；只规范化完整"日期+时刻"。

    导出时间戳通常无时区 → 输出朴素本地 ISO(YYYY-MM-DDTHH:MM:SS)，不加时区猜测。
    只有日期 / 只有时刻 / 相对时间（"昨天 23:12"）→ None（sent_at_raw 保留原文）。
    """
    if not raw:
        return None
    m = _TS_FULL.match(raw.strip())
    if not m:
        return None
    try:
        dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                      int(m.group(4)), int(m.group(5)),
                      int(m.group(6) or 0))
    except ValueError:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


# ---------------------------------------------------------------------------
# participants：初判 + 用户确认覆盖
# ---------------------------------------------------------------------------
def _empty_participant(role: str) -> dict:
    return {"role": role, "account_id": None, "names": [],
            "match_method": None, "confidence": None, "confirmed": False}


class ParticipantRegistry:
    """参与者声明表。role 的唯一权威来源。

    - add_guess(...)  ：parser 初判（confirmed=False，仅是提案，可覆盖）
    - add_manual(...) ：用户确认/覆盖（confirmed=True，最终事实，覆盖任何初判归属）
    - resolve(name, account_id) -> {role, sender_key, match_method, confidence}
    - 改昵称：把新名字并入同一 participant 的 names，resolve 自动命中。
    - 覆盖初判：add_manual 会把名字/账号从旧初判参与者上解绑并改挂到新角色。
    """

    _ROLES = ("user", "target", "other")

    def __init__(self, default_role: str = "unknown"):
        self.default_role = default_role if default_role in ("user", "target", "other", "unknown") else "unknown"
        self._participants: List[dict] = []
        self._by_account: Dict[str, dict] = {}   # normalize(account_id) -> entry
        self._by_name: Dict[str, dict] = {}      # normalize(name)      -> entry

    @property
    def participants(self) -> List[dict]:
        return self._participants

    # -- 内部 ----------------------------------------------------------
    def _entry(self, role: str) -> dict:
        for e in self._participants:
            if e["role"] == role and e["confirmed"] is False and not e["names"] and not e["account_id"]:
                return e
        e = _empty_participant(role)
        self._participants.append(e)
        return e

    def _unregister_key(self, k: str, entry: dict) -> None:
        """把 key（账号或名字）从旧 entry 解绑，避免两个 entry 同时认领。"""
        if entry is None:
            return
        if entry.get("account_id") and normalize_name(entry["account_id"]) == k:
            entry["account_id"] = None
        entry["names"] = [n for n in entry["names"] if normalize_name(n) != k]

    def _register(self, entry: dict, *, account_id: Optional[str], names: List[str]) -> None:
        if account_id:
            self._by_account[normalize_name(account_id)] = entry
            entry["account_id"] = account_id
        for n in names:
            nk = normalize_name(n)
            if nk:
                self._by_name[nk] = entry
                if n not in entry["names"]:
                    entry["names"].append(n)

    def _claim(self, role: str, *, account_id: Optional[str], names: List[str],
               match_method: Optional[str], confidence: Optional[float],
               confirmed: bool) -> dict:
        # 找到现成空壳或同角色已确认条目，避免重复
        target = None
        acct_key = normalize_name(account_id) if account_id else None
        if acct_key and acct_key in self._by_account:
            target = self._by_account[acct_key]
        else:
            for n in names:
                nk = normalize_name(n)
                if nk and nk in self._by_name:
                    target = self._by_name[nk]
                    break
        if target is not None and (target["role"] == role or confirmed):
            # 覆盖：先把名字/账号从旧归属解绑
            if acct_key:
                self._unregister_key(acct_key, self._by_account.get(acct_key))
            for n in names:
                self._unregister_key(normalize_name(n), self._by_name.get(normalize_name(n)))
            if confirmed or not target["confirmed"]:
                target["role"] = role
            target["confirmed"] = True if confirmed else target["confirmed"]
            if confirmed:
                target["match_method"] = "manual"
                target["confidence"] = 1.0
            else:
                target["match_method"] = match_method
                target["confidence"] = confidence
            self._register(target, account_id=account_id, names=names)
            return target

        entry = self._entry(role)
        entry["confirmed"] = bool(confirmed)
        entry["match_method"] = "manual" if confirmed else match_method
        entry["confidence"] = 1.0 if confirmed else confidence
        self._register(entry, account_id=account_id, names=names)
        return entry

    # -- 对外 ----------------------------------------------------------
    def add_guess(self, role: str, *, account_id: Optional[str] = None,
                  names: Optional[List[str]] = None, match_method: str = "name_exact",
                  confidence: float = 0.7) -> None:
        """parser 初判：confirmed=False，任何确认/后续材料可覆盖。"""
        if role not in self._ROLES:
            raise ValueError(f"participant role 只能 {'/'.join(self._ROLES)}，收到 {role!r}")
        self._claim(role, account_id=account_id, names=list(names or []),
                    match_method=match_method, confidence=float(confidence), confirmed=False)

    def add_manual(self, role: str, *, account_id: Optional[str] = None,
                   names: Optional[List[str]] = None) -> None:
        """用户确认/覆盖：confirmed=True，最终事实。"""
        if role not in self._ROLES:
            raise ValueError(f"participant role 只能 {'/'.join(self._ROLES)}，收到 {role!r}")
        self._claim(role, account_id=account_id, names=list(names or []),
                    match_method="manual", confidence=1.0, confirmed=True)

    def resolve(self, sender_name: Optional[str], account_id: Optional[str]) -> dict:
        """把一条消息的发送者解析为 {role, sender_key, match_method, confidence, confirmed}。

        永不返回 None；匹配不到且无双人上下文时 role 回落 default_role(=unknown)，
        绝不用"非目标即用户"来猜。confirmed 标记该角色是否已由用户确认——
        confirmed=false 的 role（尤其 target）仅是可覆盖的候选，下游不得当事实消费。
        """
        acct_key = normalize_name(account_id) if account_id else None
        name_key = normalize_name(sender_name) if sender_name else None

        entry = None
        method = "other"
        # 账号优先（最稳定，跨改昵称）
        if acct_key and acct_key in self._by_account:
            entry = self._by_account[acct_key]
            method = "account_id"
        elif name_key and name_key in self._by_name:
            entry = self._by_name[name_key]
            method = "name_exact"

        if entry is None:
            return {"role": self.default_role,
                    "sender_key": acct_key or name_key,
                    "match_method": method if (acct_key or name_key) else "other",
                    "confidence": 0.0,
                    "confirmed": False}
        # sender_key 优先账号，其次本次原始账号，再其次名字（账号稳定跨改昵称）
        sk = entry.get("account_id") or acct_key or name_key
        return {"role": entry["role"], "sender_key": sk,
                "match_method": method, "confidence": entry.get("confidence"),
                "confirmed": bool(entry.get("confirmed", False))}

    def to_list(self) -> List[dict]:
        """导出 schema 形状：去掉空壳、把 None 字段原样保留。"""
        return [dict(e) for e in self._participants if e["names"] or e.get("account_id")]


# ---------------------------------------------------------------------------
# ChatImport 组装
# ---------------------------------------------------------------------------
def build_chat_import(*, platform: str, source_format: Optional[str],
                      source_ref: str, conversation_title: Optional[str],
                      default_sender_role: str, registry: ParticipantRegistry,
                      messages: List[dict], imported_at: Optional[str] = None) -> dict:
    """组装符合 message.schema v1.1 的 ChatImport dict。"""
    return {
        "schema_version": SCHEMA_VERSION,
        "platform": platform,
        "source_format": source_format,
        "source_ref": source_ref,
        "conversation_title": conversation_title,
        "imported_at": imported_at,
        "default_sender_role": default_sender_role,
        "participants": registry.to_list(),
        "messages": messages,
    }


def write_json_utf8(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def resolve_source_ref(cli_source_ref: Optional[str], file_path: str) -> str:
    """source_ref：优先 CLI 传入的稳定 token；否则 basename 净化 slug。绝不含目录。"""
    if cli_source_ref:
        return cli_source_ref
    return slugify(basename_only(file_path))
