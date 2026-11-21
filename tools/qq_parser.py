#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QQ 聊天记录解析器（重写版，输出 message.schema.json v1.1 的 ChatImport）

真实支持的输入格式：
  1. qq_txt —— QQ 消息管理器导出的 txt。形如：
       消息分组:我的好友
       ================================================================
       消息对象:小明(123456)
       ================================================================
       2024-01-15 20:30:45 小明(123456)
       今天好累

  mht 旧版只是剥 HTML 标签、信息有损，本版显式不支持（避免"假装解析成功"）。

用法：
  python3 qq_parser.py --file chat.txt --output out.json [--target 小明] \\
      [--self-account 654321] [--source-ref token] [--conversation-title 小明]

设计要点：
  - 利用「消息对象:名字(QQ号)」头部与「时间戳 名字(QQ号)」两处 QQ 号，把 account_id
    带进 participants，改昵称也能靠 QQ 号稳定归人。
  - 文件若含多个「消息对象」会话（=群聊/多会话），拆成多个 ChatImport 输出
    （写 output 目录），默认取第一个会话来构造标题。
  - 双人聊天且未给 --target 时，非你方即推断为 target（position，可被确认覆盖）。
  - 无法确定 sender 或消息行 → 显式警告并给 unknown/丢弃计数，绝不静默吞。
  - txt 无媒体类型模型 → content_type=null；[图片]/[语音] 占位符原样留 body。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from chat_parser_common import (
    ParserError, UnsupportedFormatError, EncodingError,
    ParticipantRegistry, normalize_name, normalize_timestamp,
    compute_message_id, compute_content_fingerprint, assert_unique_ids,
    build_chat_import, write_json_utf8, resolve_source_ref, read_text_file,
    basename_only, log,
)

PLATFORM = "qq"

_SESSION_SEP_RE = re.compile(r"^={5,}\s*$")
_MSG_OBJECT_RE = re.compile(r"^消息对象[:：]\s*(.+?)(?:\((\d{3,})\))?\s*$")
_MSG_GROUP_RE = re.compile(r"^消息分组[:：]\s*(.*?)\s*$")
_QQ_BOILER_RE = re.compile(r"^消息记录")   # QQ 导出文件头的固定说明行
_MSG_HEAD_RE = re.compile(
    r"^(\d{4})-(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{2})(?::(\d{2}))?\s+(.+?)\s*$"
)


# ---------------------------------------------------------------------------
# 结构：把文本切成会话段
# ---------------------------------------------------------------------------
class _Session:
    def __init__(self, title: str, account: Optional[str], start_line: int):
        self.title = title
        self.account = account            # 会话对端账号（消息对象 行给出）
        self.header_lines: List[str] = [] # 会话头原文（元信息：分组/分隔线）
        self.body_lines: List[str] = []
        self.start_line = start_line


def _split_sessions(text: str, filename: str) -> Tuple[List[_Session], List[str]]:
    """按『消息对象:名字』块切分；没有 消息对象 头但有消息头时，以分组头起一个会话。

    状态机：分组头/分隔线是"前置元信息"，归属于下一个真正含消息的会话；
    不含消息的分组头不会产生空会话。
    """
    lines = text.splitlines()
    sessions: List[_Session] = []
    cur: Optional[_Session] = None
    preamble: List[str] = []      # 尚未归属的 消息分组/分隔线
    pending_group_title = ""      # 最近一个 消息分组:xxx 的名字
    dropped = 0
    first_nonmeta_line = 1

    def open_session(title: str, account: Optional[str], at_line: int):
        nonlocal cur, preamble
        if cur is not None and any(l.strip() for l in cur.body_lines):
            sessions.append(cur)   # 关闭上一个会话（仅当它真的有内容）
        cur = _Session(title=title or pending_group_title, account=account, start_line=at_line)
        cur.header_lines = list(preamble)
        preamble = []

    for i, line in enumerate(lines, 1):
        s = line.strip()
        if not s:
            if cur is not None:
                cur.body_lines.append(line)
            continue
        m_group = _MSG_GROUP_RE.match(s)
        if m_group:
            pending_group_title = m_group.group(1).strip()
            preamble.append(line)
            continue
        if _SESSION_SEP_RE.match(s):
            preamble.append(line)
            continue
        if _QQ_BOILER_RE.match(s):
            preamble.append(line)   # 文件头说明行（"消息记录（…）"），归属元信息
            continue
        m_obj = _MSG_OBJECT_RE.match(s)
        if m_obj:
            # 消息对象 行是标题行，归属前置元信息
            name = m_obj.group(1).strip()
            acct = m_obj.group(2)
            preamble.append(line)
            open_session(name, acct, i)
            continue
        # 正文（可能是消息头，也可能是内容行）
        if cur is None:
            # 尚无会话：若这行是消息头且已有分组头，则用分组头开一个会话
            if _MSG_HEAD_RE.match(s) and (preamble or pending_group_title):
                open_session("", None, i)
                cur.body_lines.append(line)
                continue
            first_nonmeta_line = i if first_nonmeta_line == 1 else first_nonmeta_line
            dropped += 1
            continue
        cur.body_lines.append(line)

    if cur is not None:
        sessions.append(cur)
    # 丢弃没接正文的空会话（只含元信息的分组头）
    sessions = [s for s in sessions if any(l.strip() for l in s.body_lines)]

    if not sessions:
        raise ParserError(
            "未解析到任何含消息的会话：请确认是 QQ 消息管理器导出的 txt（含『消息对象』或消息头）",
            filename=filename, fmt="qq_txt")
    warns = []
    if dropped:
        warns.append(f"丢弃 {dropped} 行无法归属的杂散内容（首个会话前，第 {first_nonmeta_line} 行起）")
    return sessions, warns


# ---------------------------------------------------------------------------
# 解析单个会话的消息
# ---------------------------------------------------------------------------
def _parse_session_messages(session: _Session, filename: str) -> Tuple[List[dict], List[str]]:
    raw: List[dict] = []
    cur = None
    warnings: List[str] = []

    def finalize():
        nonlocal cur
        if cur is None:
            return
        lines = cur["lines"]
        while lines and lines[0].strip() == "":
            lines.pop(0)
        while lines and lines[-1].strip() == "":
            lines.pop()
        body = "\n".join(lines)
        raw.append({"sent_at_raw": cur["sent_at_raw"], "sender_name": cur["sender_name"],
                    "account_id": cur["account_id"], "body": body})
        cur = None

    for idx, line in enumerate(session.body_lines):
        approx_line = session.start_line + idx
        m = _MSG_HEAD_RE.match(line)
        if m:
            finalize()
            sender_field = m.group(7).strip()
            sender_name, account_id = _split_sender_field(sender_field)
            ts_raw = f"{m.group(1)}-{m.group(2)}-{m.group(3)} {m.group(4)}:{m.group(5)}"
            if m.group(6):
                ts_raw += f":{m.group(6)}"
            cur = {"sent_at_raw": ts_raw, "sender_name": sender_name,
                   "account_id": account_id, "lines": []}
            continue
        if cur is not None:
            cur["lines"].append(line)
            continue
        # 尚无打开的当前消息
        if line.strip() == "":
            continue  # 消息间隔空行，静默跳过
        # 真·孤儿内容（第一个消息头之前），warning
        warnings.append(f"line ~{approx_line}: 消息头之前出现非空内容，已忽略")
    finalize()
    return raw, warnings


def _split_sender_field(field: str) -> Tuple[str, Optional[str]]:
    """把发送者字段拆成 (名字, QQ号)。如 '小明(123456)'、'我(654321)'、'小明'。"""
    m = re.match(r"^(.*?)\((\d{3,})\)$", field.strip())
    if m:
        return m.group(1).strip(), m.group(2)
    return field.strip(), None


# ---------------------------------------------------------------------------
# participants 初判（按会话）
# ---------------------------------------------------------------------------
def _build_registry(session: _Session, target_aliases: List[str],
                    self_accounts: List[str], self_names: List[str],
                    body_labels: List[str]) -> Tuple[ParticipantRegistry, List[str]]:
    # 会话里出现 ≥3 个不同说话人 → 群聊：匹配不到 user/target 的发送者应归 other（而非 unknown）
    distinct = sorted({l for l in body_labels} | {session.title} if session.title else {l for l in body_labels})
    is_group = len(distinct) >= 3
    default_role = "other" if is_group else "unknown"
    reg = ParticipantRegistry(default_role=default_role)
    warnings: List[str] = []
    if is_group:
        warnings.append(f"检测到 {len(distinct)} 个说话人，判定为群聊：未知成员回落 role=other。")

    # 你本人：优先 --self-account（QQ号最可靠）
    if self_accounts:
        for a in self_accounts:
            reg.add_guess("user", account_id=a, match_method="account_id", confidence=0.95)
    if self_names:
        reg.add_guess("user", names=self_names, match_method="name_exact", confidence=0.85)

    # 目标：优先 --target
    if target_aliases:
        for t in target_aliases:
            if t.isdigit() and len(t) >= 3:
                reg.add_guess("target", account_id=t, match_method="account_id", confidence=0.9)
            else:
                reg.add_guess("target", names=[t], match_method="name_exact", confidence=0.9)
        # 若给了名字但没给号，把单聊会话头的账号绑到目标上（更稳定）；群聊不绑（群号≠目标账号）
        if session.account and session.account not in self_accounts and not is_group:
            has_acct = any(
                p["role"] == "target" and p["account_id"] == session.account
                for p in reg.to_list())
            if not has_acct:
                reg.add_guess("target", account_id=session.account,
                              match_method="account_id", confidence=0.9)
        return reg, warnings

    # 无 --target：绝不把「消息对象 头」或「唯一对方」直接当成 target 事实。
    # 仅在已锚定 user（self-*）且确为双人时，把唯一对方登记为低置信候选(confirmed=false)；
    # 否则保持 unknown（错误的 target 比 unknown 更危险）。
    if self_accounts or self_names:
        others = [l for l in body_labels if l not in self_names]
        if not session.account and len(set(others)) == 1:
            only = sorted(set(others))[0]
            reg.add_guess("target", names=[only], match_method="position", confidence=0.5)
            warnings.append(f"未提供 --target：把唯一对方『{only}』登记为低置信 target 候选"
                            f"(confidence 0.5, confirmed=false)，不会进入 Persona/Memory；请确认或 --target 覆盖。")
            return reg, warnings
        if session.account and len(set(others)) <= 1:
            # 会话头 + user 已锚定的双人：把对端作为低置信候选
            reg.add_guess("target", account_id=session.account,
                          names=[session.title] if session.title else [],
                          match_method="position", confidence=0.5)
            warnings.append(f"未提供 --target：按会话头把『{session.title}』(QQ {session.account}) 登记为"
                            f"低置信 target 候选(confidence 0.5, confirmed=false)，请确认或 --target 覆盖。")
            return reg, warnings
        warnings.append("未提供 --target 且非双人场景：无法判定目标，其余人 role=unknown/other。请用 --target 指定。")
    else:
        warnings.append("未提供 --self* 与 --target：无法锚定 user 与 target，双方保持 unknown。"
                        "错误的 target 比 unknown 更危险。")
    return reg, warnings


def _collect_body_labels(body_lines: List[str], filename: str) -> List[str]:
    labels: List[str] = []
    for line in body_lines:
        m = _MSG_HEAD_RE.match(line)
        if m:
            name, _acct = _split_sender_field(m.group(7).strip())
            if name and name not in labels:
                labels.append(name)
    return labels


# ---------------------------------------------------------------------------
# 组装
# ---------------------------------------------------------------------------
def _emit(session: _Session, raw: List[dict], reg: ParticipantRegistry,
          source_ref: str, source_format: str, warnings: List[str]) -> dict:
    messages: List[dict] = []
    for seq, r in enumerate(raw):
        sender_name = r.get("sender_name")
        resolved = reg.resolve(sender_name, r.get("account_id"))
        body = r.get("body", "")
        sent_at = normalize_timestamp(r.get("sent_at_raw") or "")
        messages.append({
            "id": compute_message_id(PLATFORM, resolved["sender_key"], r.get("sent_at_raw"),
                                     body, None, seq),
            "content_fingerprint": compute_content_fingerprint(
                PLATFORM, resolved["sender_key"], r.get("sent_at_raw"), body, None),
            "sequence": seq,
            "sent_at": sent_at,
            "sent_at_raw": r.get("sent_at_raw"),
            "sender": {"role": resolved["role"], "name": sender_name,
                       "sender_key": resolved["sender_key"]},
            "content_type": None,
            "body": body,
            "media": None,
            "reply_to_message_id": None,
            "is_recalled": None,
            "in_group_chat": None,
        })
    assert_unique_ids(messages)
    title = session.title or None
    return build_chat_import(platform=PLATFORM, source_format=source_format,
                             source_ref=source_ref, conversation_title=title,
                             default_sender_role="unknown", registry=reg,
                             messages=messages, imported_at=datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))


# ---------------------------------------------------------------------------
# 库接口：解析文件 → ChatImport（供 import_pipeline 直接调用）
# ---------------------------------------------------------------------------
def parse_file_to_import(*, file: str, target: str = "", self_account: str = "",
                         self_names: str = "", source_ref: Optional[str] = None,
                         conversation_title: Optional[str] = None) -> dict:
    """解析单个 QQ 文件（可能含多个会话），返回结构化结果（不做任何文件写出）。

    返回 dict:
      ok            bool
      error         str|None
      imports       list[ {chat_import, warnings} ]   每个会话一个（多会话时 source_ref 带 __sessionN）
      batch_warnings list[str]
    """
    result = {"ok": False, "error": None, "imports": [], "batch_warnings": []}
    target_aliases = [t.strip() for t in target.split(",") if t.strip()]
    self_accounts = [a.strip() for a in self_account.split(",") if a.strip()]
    self_list = [a.strip() for a in self_names.split(",") if a.strip()]
    try:
        text = read_text_file(file)
        lower = file.lower()
        if lower.endswith((".mht", ".mhtml")):
            raise UnsupportedFormatError(
                "QQ mht 导出本版不支持：旧实现剥 HTML 标签有损。请用 QQ 导出的 txt（消息管理器）重导。",
                filename=basename_only(file), fmt="mht")
        if not lower.endswith(".txt"):
            raise UnsupportedFormatError("QQ 解析仅支持 .txt 导出", filename=basename_only(file),
                                         fmt=lower.split('.')[-1] if '.' in lower else "unknown")

        sessions, s_warn = _split_sessions(text, basename_only(file))
        log(f"[qq] 文件: {basename_only(file)}  会话数: {len(sessions)}")
        multi = len(sessions) > 1
        base_sref = resolve_source_ref(source_ref, file)

        for si, session in enumerate(sessions):
            body_labels = _collect_body_labels(session.body_lines, basename_only(file))
            reg, warn0 = _build_registry(session, target_aliases, self_accounts,
                                         self_list, body_labels)
            raw, warn1 = _parse_session_messages(session, basename_only(file))
            sref = f"{base_sref}__session{si + 1}" if multi else base_sref
            title = conversation_title or session.title
            data = _emit(session, raw, reg, sref, "txt",
                         warn0 + warn1 + s_warn)
            result["imports"].append({
                "chat_import": data,
                "warnings": list(warn0 + warn1 + s_warn),
            })
        result["ok"] = True
        result["batch_warnings"] = list(s_warn)
        return result
    except (ParserError, EncodingError) as e:
        result["ok"] = False
        result["error"] = str(e)
        return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="QQ 聊天记录解析器 → ChatImport JSON (message.schema v1.2)")
    ap.add_argument("--file", required=True, help="输入文件路径")
    ap.add_argument("--output", required=True, help="输出 JSON 路径（多会话时作为目录，每个会话写一个文件）")
    ap.add_argument("--target", default="", help="目标人格名字或QQ号，逗号分隔")
    ap.add_argument("--self-account", default="", help="你本人的QQ号，逗号分隔（最可靠）")
    ap.add_argument("--self-names", default="", help="你本人的名字/备注，逗号分隔")
    ap.add_argument("--source-ref", default=None, help="稳定导入源 ID（不含路径）")
    ap.add_argument("--conversation-title", default=None, help="覆盖会话标题")
    args = ap.parse_args(argv)

    res = parse_file_to_import(file=args.file, target=args.target,
                               self_account=args.self_account,
                               self_names=args.self_names, source_ref=args.source_ref,
                               conversation_title=args.conversation_title)
    if not res["ok"]:
        log(f"[qq] 错误: {res['error']}")
        return 2

    outputs: List[str] = []
    multi = len(res["imports"]) > 1
    if multi:
        os.makedirs(args.output, exist_ok=True)
    for si, entry in enumerate(res["imports"]):
        data = entry["chat_import"]
        title = data.get("conversation_title") or f"session{si + 1}"
        for w in entry["warnings"]:
            log(f"[qq] 会话{si + 1} 警告: {w}")
        if multi:
            safe = re.sub(r"[^\w一-鿿]+", "_", title).strip("_") or f"session{si + 1}"
            out_path = os.path.join(args.output, f"{safe}.json")
        else:
            out_path = args.output
        write_json_utf8(out_path, data)
        outputs.append(out_path)
        roles = Counter(m["sender"]["role"] for m in data["messages"])
        log(f"[qq] 会话{si + 1}『{title}』: {len(data['messages'])} 条 → {out_path}  角色 {dict(roles)}")
    log(f"[qq] 完成: {len(outputs)} 个文件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
