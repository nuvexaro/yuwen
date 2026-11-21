#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""微信聊天记录解析器（重写版，输出 message.schema.json v1.1 的 ChatImport）

真实支持的输入格式（只认这些，其余显式报错，绝不静默当 plaintext 假装成功）：
  1. wechatmsg_txt   —— WeChatMsg / 留痕等导出的「时间戳 + 发送者 + 内容行」txt
  2. liuhen_json     —— 留痕类导出的 JSON（含 WeChat msgType 时才给 content_type）

明确不支持：csv / sqlite / db / html —— 旧版空声明，本版不伪造能力。

用法示例：
  python3 wechat_parser.py --file chat.txt --target 小明 --output out.json [--self-names 我] \\
      [--source-ref 2024-01-15] [--format auto] [--default-sender-role unknown] \\
      [--conversation-title 小明]

安全与诚实：
  - 逐条保真：sender 名/sent_at_raw/body(换行·错别字·emoji·占位符) 原样保留，绝不合并连发、绝不压换行。
  - 不猜：猜不出 sender 角色 → role=unknown（回落 default_sender_role）；猜不出时间 → sent_at=null；
    txt 无类型模型 → content_type=null（[图片] 占位符留 body，绝不伪造 media/image）。
  - participants 是「初判」(confirmed=false)，可被后续用户确认覆盖。
  - 日志只打文件名 basename 与计数，不打全路径、不打正文。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from typing import List, Optional, Tuple

from chat_parser_common import (
    ParserError, UnsupportedFormatError, EncodingError,
    ParticipantRegistry, normalize_name, normalize_timestamp,
    compute_message_id, compute_content_fingerprint, assert_unique_ids,
    build_chat_import, write_json_utf8, resolve_source_ref, read_text_file,
    basename_only, log,
)

SUPPORTED_FORMATS = ("auto", "wechatmsg_txt", "liuhen_json")
PLATFORM = "wechat"

_HEADER_RE = re.compile(
    r"^(\d{4})-(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{2})(?::(\d{2}))?\s+(.+?)\s*$"
)
# 相对日期头（昨天/今天/前天 HH:MM[:SS] 发送者）：保留 raw，不猜具体日期
_RELA_HEAD_RE = re.compile(r"^(昨天|今天|前天)\s+(\d{1,2}):(\d{2})(?::(\d{2}))?\s+(.+?)\s*$")
_WEIXIN_MSGTYPE = {
    1: "text", 3: "image", 34: "audio", 42: "contact", 43: "video",
    47: "sticker", 48: "location", 49: "unknown", 10000: "system",
}


# ---------------------------------------------------------------------------
# 格式检测
# ---------------------------------------------------------------------------
def _looks_like_wechat_txt(text: str) -> bool:
    for line in text.splitlines():
        if not line.strip():
            continue
        return bool(_HEADER_RE.match(line))
    return False


def detect_format(file_path: str, text: str, forced: str) -> str:
    if forced in ("wechatmsg_txt", "liuhen_json"):
        return forced
    lower = file_path.lower()
    if lower.endswith(".json"):
        return "liuhen_json"
    if lower.endswith((".csv", ".db", ".sqlite", ".sqlite3", ".html", ".htm")):
        raise UnsupportedFormatError(
            f"{lower.split('.')[-1]} 格式本版不支持：旧代码对它是空声明。请改用 WeChatMsg/留痕 的 txt 或 json 导出。",
            filename=basename_only(file_path), fmt=lower.split('.')[-1])
    if lower.endswith(".txt") or lower.endswith(".log"):
        if _looks_like_wechat_txt(text):
            return "wechatmsg_txt"
        raise UnsupportedFormatError(
            "txt 中没有识别到「YYYY-MM-DD HH:MM:SS 发送者」消息头。手动粘贴/无结构文本本版不支持"
            "（无法可靠拆分逐条消息），请提供带时间戳的结构化导出。",
            filename=basename_only(file_path), fmt="txt")
    raise UnsupportedFormatError(f"无法识别的扩展名 {file_path.rsplit('.', 1)[-1] if '.' in file_path else '(无扩展名)'}",
                                 filename=basename_only(file_path))


# ---------------------------------------------------------------------------
# participants 初判
# ---------------------------------------------------------------------------
def build_registry_txt(text: str, target_aliases: List[str],
                       self_names: List[str]) -> Tuple[ParticipantRegistry, List[str]]:
    reg = ParticipantRegistry(default_role="unknown")
    warnings: List[str] = []
    labels = _collect_labels(text)
    non_me = [l for l in labels if l != "我"]

    # 你本人：仅当能可靠锚定 user 时才登记；锚定不了则整体保持 unknown
    user_anchored = False
    if self_names:
        reg.add_guess("user", names=self_names, match_method="name_exact", confidence=0.85)
        user_anchored = True
    elif "我" in labels:
        reg.add_guess("user", names=["我"], match_method="name_exact", confidence=0.85)
        user_anchored = True
    else:
        warnings.append("未提供 --self-names 且未找到『我』标签：无法标记你本人，双方都保持 unknown。")

    if target_aliases:
        for t in target_aliases:
            reg.add_guess("target", names=[t], match_method="name_exact", confidence=0.9)
    elif user_anchored and len(non_me) == 1:
        # 已锚定 user 且双人 → 唯一对方作为低置信 target 候选（confirmed=false，仅供用户确认）
        only = non_me[0]
        reg.add_guess("target", names=[only], match_method="position", confidence=0.5)
        warnings.append(f"未提供 --target：把唯一对方『{only}』登记为低置信 target 候选(confidence 0.5, "
                       f"confirmed=false)。此猜测不会进入 Persona/Memory；请确认或 --target 覆盖。")
    else:
        # 无 user 锚点、或多人 —— 绝不用「位置」猜 target
        if target_aliases:
            pass
        elif not user_anchored:
            warnings.append("无法锚定 user 与 target：双方保持 unknown。请用 --self-names/--target 指定。")
        else:
            warnings.append("检测到多个说话人：无法判定谁是被蒸馏目标，除你外其余 role=unknown。请用 --target 指定。")
    return reg, warnings


def _collect_labels(text: str) -> List[str]:
    labels: List[str] = []
    for line in text.splitlines():
        m = _HEADER_RE.match(line)
        name = m.group(7).strip() if m else None
        if name is None:
            m_rel = _RELA_HEAD_RE.match(line)
            name = m_rel.group(5).strip() if m_rel else None
        if name and name not in labels:
            labels.append(name)
    return labels


# ---------------------------------------------------------------------------
# 解析：wechatmsg_txt
# ---------------------------------------------------------------------------
def parse_wechat_txt(text: str, filename: str) -> Tuple[List[dict], List[str]]:
    """逐条消息。content 行缓冲，跨空行分割为独立消息，绝不合并连发。"""
    raw: List[dict] = []          # 每元素: sent_at_raw / sender_name / lines[]
    cur = None
    line_no = 0
    warnings: List[str] = []

    def finalize():
        nonlocal cur
        if cur is None:
            return
        body_lines = cur["lines"]
        # 去掉首尾空行（它们是消息间分隔符），保留内部空行=段落空行
        while body_lines and body_lines[0] == "":
            body_lines.pop(0)
        while body_lines and body_lines[-1] == "":
            body_lines.pop()
        body = "\n".join(body_lines)
        raw.append({"sent_at_raw": cur["sent_at_raw"], "sender_name": cur["sender_name"],
                    "body": body, "start_line": cur["start_line"]})
        cur = None

    for line in text.splitlines():
        line_no += 1
        m = _HEADER_RE.match(line)
        if m:
            finalize()
            ts_raw = f"{m.group(1)}-{m.group(2)}-{m.group(3)} {m.group(4)}:{m.group(5)}"
            if m.group(6):
                ts_raw += f":{m.group(6)}"
            cur = {"sent_at_raw": ts_raw, "sender_name": m.group(7).strip(),
                   "lines": [], "start_line": line_no}
            continue
        m_rel = _RELA_HEAD_RE.match(line)
        if m_rel:
            # 相对日期头：保留 raw（sent_at 由 normalize_timestamp 置 null），发送者照常解析
            finalize()
            ts_raw = f"{m_rel.group(1)} {m_rel.group(2)}:{m_rel.group(3)}"
            if m_rel.group(4):
                ts_raw += f":{m_rel.group(4)}"
            cur = {"sent_at_raw": ts_raw, "sender_name": m_rel.group(5).strip(),
                   "lines": [], "start_line": line_no}
            continue
        if cur is not None:
            cur["lines"].append(line)
            continue
        if line.strip():
            warnings.append(f"line {line_no}: 在第一条消息头之前出现非空内容，已忽略")

    finalize()
    if not raw:
        raise ParserError("没有解析到任何消息（文件可能是空导出或格式不符）",
                          filename=filename, fmt="wechatmsg_txt")
    return raw, warnings


# ---------------------------------------------------------------------------
# 解析：liuhen_json
# ---------------------------------------------------------------------------
def _decode_json_messages(data, filename: str) -> List[dict]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("messages", "data", "msg", "list"):
            if isinstance(data.get(key), list):
                return data[key]
    raise ParserError("JSON 结构无法识别：期望数组或含 messages/data 列表的对象",
                      filename=filename, fmt="liuhen_json")


def _json_field(msg: dict, *keys):
    for k in keys:
        if k in msg and msg[k] is not None and msg[k] != "":
            return msg[k]
    return None


def parse_liuhen_json(text: str, filename: str) -> Tuple[List[dict], List[str]]:
    warnings: List[str] = []
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ParserError(f"JSON 解析失败: {e.msg} (line {e.lineno} col {e.colno})",
                          filename=filename, fmt="liuhen_json")
    msg_list = _decode_json_messages(data, filename)
    raw: List[dict] = []

    for idx, item in enumerate(msg_list):
        if not isinstance(item, dict):
            warnings.append(f"第 {idx} 条不是对象，跳过")
            continue
        sender = _json_field(item, "sender", "nickname", "from", "name", "talker")
        ts = _json_field(item, "time", "timestamp", "createTime", "msgTime", "date")
        body = _json_field(item, "content", "message", "text", "strContent", "body")
        body = body if body is not None else ""
        # 时间可能是毫秒/秒级时间戳或字符串
        ts_raw = _coerce_timestamp(ts)
        # msgType（WeChat 类型号）仅在能确证时用
        content_type = None
        mt = item.get("type", item.get("msgType"))
        if isinstance(mt, (int, float)) and int(mt) in _WEIXIN_MSGTYPE:
            content_type = _WEIXIN_MSGTYPE[int(mt)]
        elif isinstance(mt, str):
            s = mt.strip().lower()
            if s in ("text", "image", "audio", "voice", "video", "sticker", "file",
                     "link", "location", "contact", "system"):
                content_type = "voice" if s == "voice" else s
        raw.append({"sent_at_raw": ts_raw, "sender_name": str(sender).strip() if sender is not None else None,
                    "body": body, "content_type": content_type,
                    "is_recalled": item.get("is_recalled", item.get("recalled")) if isinstance(
                        item.get("is_recalled", item.get("recalled")), bool) else None,
                    "start_line": idx})
    if not raw:
        raise ParserError("JSON 中没有解析到消息", filename=filename, fmt="liuhen_json")
    return raw, warnings


def _coerce_timestamp(ts) -> Optional[str]:
    """把时间戳字段转成可展示的字符串原文；只把秒级/毫秒级整数时间戳规范化为 ISO。"""
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        # 秒 vs 毫秒
        if ts > 10_000_000_000:  # 毫秒
            ts_s = ts / 1000.0
        else:
            ts_s = ts
        try:
            return datetime.fromtimestamp(ts_s).strftime("%Y-%m-%d %H:%M:%S")
        except (OSError, ValueError, OverflowError):
            return str(ts)
    s = str(ts).strip()
    if not s:
        return None
    return s


# ---------------------------------------------------------------------------
# 组装 ChatImport
# ---------------------------------------------------------------------------
def _emit(raw_msgs: List[dict], reg: ParticipantRegistry, title: str,
          source_ref: str, warnings: List[str], filename: str,
          source_format: Optional[str] = None) -> dict:
    messages: List[dict] = []
    seq = 0
    for r in raw_msgs:
        sender_name = r.get("sender_name")
        body = r.get("body")
        body_str = body if isinstance(body, str) else ("" if body is None else str(body))
        resolved = reg.resolve(sender_name, r.get("account_id"))
        sent_at = normalize_timestamp(r.get("sent_at_raw") or "")
        content_type = r.get("content_type") if "content_type" in r else None
        msg = {
            "id": compute_message_id(PLATFORM, resolved["sender_key"], r.get("sent_at_raw"),
                                     body_str, content_type, seq),
            "content_fingerprint": compute_content_fingerprint(
                PLATFORM, resolved["sender_key"], r.get("sent_at_raw"),
                body_str, content_type),
            "sequence": seq,
            "sent_at": sent_at,
            "sent_at_raw": r.get("sent_at_raw"),
            "sender": {
                "role": resolved["role"],
                "name": sender_name,
                "sender_key": resolved["sender_key"],
            },
            "content_type": content_type,
            "body": body_str,
            "media": None,
            "reply_to_message_id": None,
            "is_recalled": r.get("is_recalled"),
            "in_group_chat": None,
        }
        if msg["sender"]["name"] is None:
            warnings.append(f"消息 #{seq} 缺发送者，role=unknown")
        messages.append(msg)
        seq += 1
    assert_unique_ids(messages, filename="")
    return build_chat_import(platform=PLATFORM, source_format=source_format,
                             source_ref=source_ref, conversation_title=title or None,
                             default_sender_role="unknown", registry=reg,
                             messages=messages, imported_at=datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))


# ---------------------------------------------------------------------------
# 库接口：解析文件 → ChatImport（供 import_pipeline 直接调用）
# ---------------------------------------------------------------------------
def parse_file_to_import(*, file: str, target: str = "", self_names: str = "",
                         source_ref: Optional[str] = None, format: str = "auto",
                         conversation_title: Optional[str] = None) -> dict:
    """解析单个微信文件，返回结构化结果（不做任何文件写出）。

    返回 dict:
      ok            bool
      error         str|None   失败时的可诊断信息
      imports       list[ {chat_import, warnings} ]   通常 1 个
      batch_warnings list[str]  与具体 import 无关的文件级警告
    """
    result = {"ok": False, "error": None, "imports": [], "batch_warnings": []}
    target_aliases = [a.strip() for a in target.split(",") if a.strip()]
    self_list = [a.strip() for a in self_names.split(",") if a.strip()]
    try:
        text = read_text_file(file)
        fmt = detect_format(file, text, format)
        log(f"[wechat] 格式: {fmt}  文件: {basename_only(file)}")
        if fmt == "wechatmsg_txt":
            reg, warn0 = build_registry_txt(text, target_aliases, self_list)
            raw, warn1 = parse_wechat_txt(text, basename_only(file))
        else:  # liuhen_json
            reg, warn0 = _build_registry_json(target_aliases)
            raw, warn1 = parse_liuhen_json(text, basename_only(file))
        warnings = warn0 + warn1
        sref = resolve_source_ref(source_ref, file)
        title = conversation_title or _infer_title(raw)
        # source_format 用 schema 词表（文件级格式）；内部 fmt 是解析器探测的导出风格
        schema_format = {"wechatmsg_txt": "txt", "liuhen_json": "json"}.get(fmt, fmt)
        chat_import = _emit(raw, reg, title, sref, warnings, basename_only(file),
                            source_format=schema_format)
        result["ok"] = True
        result["imports"] = [{"chat_import": chat_import, "warnings": list(warnings)}]
        return result
    except (ParserError, EncodingError) as e:
        result["ok"] = False
        result["error"] = str(e)
        return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="微信聊天记录解析器 → ChatImport JSON (message.schema v1.2)")
    ap.add_argument("--file", required=True, help="输入文件路径")
    ap.add_argument("--output", required=True, help="输出 JSON 路径")
    ap.add_argument("--target", default="", help="目标人格名字/别名，逗号分隔")
    ap.add_argument("--self-names", default="", help="你本人在这份记录里的名字/别名，逗号分隔")
    ap.add_argument("--source-ref", default=None, help="稳定导入源 ID（不含路径）；缺省用文件 basename")
    ap.add_argument("--format", default="auto", choices=SUPPORTED_FORMATS, help="强制格式")
    ap.add_argument("--conversation-title", default=None, help="会话标题覆盖")
    args = ap.parse_args(argv)

    res = parse_file_to_import(file=args.file, target=args.target,
                               self_names=args.self_names, source_ref=args.source_ref,
                               format=args.format, conversation_title=args.conversation_title)
    if not res["ok"]:
        log(f"[wechat] 错误: {res['error']}")
        return 2
    for entry in res["imports"]:
        data = entry["chat_import"]
        write_json_utf8(args.output, data)
        role_count = {}
        for m in data["messages"]:
            role_count[m["sender"]["role"]] = role_count.get(m["sender"]["role"], 0) + 1
        log(f"[wechat] 完成: {len(data['messages'])} 条消息 → {args.output}")
        log(f"[wechat] 角色分布: {role_count}")
        for w in entry["warnings"]:
            log(f"[wechat] 警告: {w}")
    return 0


def _build_registry_json(target_aliases: List[str]):
    reg = ParticipantRegistry(default_role="unknown")
    warnings: List[str] = []
    if target_aliases:
        reg.add_guess("target", names=target_aliases, match_method="name_exact", confidence=0.9)
    else:
        warnings.append("JSON 导出请提供 --target（对方名字），否则目标消息 role=unknown。")
    return reg, warnings


def _infer_title(raw: List[dict]) -> Optional[str]:
    # 用最常见的目标名作标题；不强求
    from collections import Counter
    c = Counter(r.get("sender_name") for r in raw if r.get("sender_name"))
    if c:
        return c.most_common(1)[0][0]
    return None


if __name__ == "__main__":
    sys.exit(main())
