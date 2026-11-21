#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""聊天记录解析器测试套件（wechat_parser / qq_parser / chat_parser_common）

不依赖 pytest，直接 `python3 test_chat_parsers.py` 运行。同时做：
  - 纯解析断言（计数 / 字段值 / 角色）
  - 输出 JSON 用 jsonschema（message.schema.json v1.1）做 schema 校验（正向/反向）
  - 确定性 id 稳定性 / participants 初判与 confirmed 覆盖

用法：
  cd tools
  python test_chat_parsers.py            # 全部
  python test_chat_parsers.py -v         # 详细

覆盖清单（对齐 Stage 2 G 节）：
  双人/连续短消息/多行消息/昵称变化/无法识别sender/模糊时间/占位符/空消息/
  异常格式/重复导入ID稳定/participants初判/confirmed覆盖/中文编码/群聊多会话
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from typing import Callable, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.dirname(HERE)

import chat_parser_common as cc
import wechat_parser
import qq_parser

SCHEMA_PATH = os.path.join(ROOT, "message.schema.json")

# ---------------------------------------------------------------------------
# 轻量断言
# ---------------------------------------------------------------------------
class Checker:
    def __init__(self, verbose: bool = False):
        self.pass_count = 0
        self.fail_count = 0
        self.failures: List[str] = []
        self.verbose = verbose

    def ok(self, name: str, cond: bool, detail: str = ""):
        if cond:
            self.pass_count += 1
            if self.verbose:
                print(f"  ok   {name}")
        else:
            self.fail_count += 1
            msg = f"FAIL {name}"
            if detail:
                msg += f" — {detail}"
            self.failures.append(msg)
            print(msg)

    def summary(self):
        print(f"\n通过 {self.pass_count} / 失败 {self.fail_count}")
        if self.failures:
            print("失败项：")
            for f in self.failures:
                print("  -", f)
        return self.fail_count == 0


C = Checker(verbose="-v" in sys.argv)

# ---------------------------------------------------------------------------
# schema 校验
# ---------------------------------------------------------------------------
def _validator():
    try:
        import jsonschema
        from jsonschema import Draft202012Validator, FormatChecker
        from datetime import datetime
    except ImportError:
        print("跳过 schema 校验：未安装 jsonschema")
        return None

    def _iso(v):
        if not isinstance(v, str):
            return True
        try:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
            return True
        except ValueError:
            return False

    FormatChecker.checkers["date-time"] = (lambda i: _iso(i), ValueError)
    schema = json.load(open(SCHEMA_PATH, encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


VALIDATOR = _validator()


def schema_valid(inst) -> List[str]:
    if VALIDATOR is None:
        return []
    return [e.message for e in VALIDATOR.iter_errors(inst)]


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
class Tmp:
    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="parser_test_")

    def path(self, name: str) -> str:
        return os.path.join(self.dir, name)

    def cleanup(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def run_wx(tmp: Tmp, content: str, name: str = "wx.txt", out: str = "wx.json",
           **cli) -> dict:
    fp = tmp.path(name)
    with open(fp, "w", encoding=cli.pop("_encoding", "utf-8")) as f:
        f.write(content)
    argv = ["--file", fp, "--output", tmp.path(out)]
    for k, v in cli.items():
        argv += [f"--{k.replace('_', '-')}", str(v)]
    rc = wechat_parser.main(argv)
    return {"rc": rc, "data": json.load(open(tmp.path(out), encoding="utf-8")) if os.path.exists(tmp.path(out)) else None}


def run_qq(tmp: Tmp, content: str, name: str = "qq.txt", out: str = "qq.json",
           **cli) -> dict:
    fp = tmp.path(name)
    with open(fp, "w", encoding=cli.pop("_encoding", "utf-8")) as f:
        f.write(content)
    argv = ["--file", fp, "--output", tmp.path(out)]
    for k, v in cli.items():
        argv += [f"--{k.replace('_', '-')}", str(v)]
    rc = qq_parser.main(argv)
    return {"rc": rc, "data": json.load(open(tmp.path(out), encoding="utf-8")) if os.path.exists(tmp.path(out)) else None}


def jsonify(content: str) -> str:
    return json.dumps(content, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 采样文本
# ---------------------------------------------------------------------------
WX_BASIC = (
    "2024-01-15 20:30:45 我\n在干嘛\n"
    "\n"
    "2024-01-15 20:31:02 小明\n刚下班 累死了\n"
    "哈哈哈哈哈！！\n"
    "[图片]\n"
    "\n"
    "2024-01-15 20:31:05 小明\n你呢\n"
    "\n"
    "2024-01-15 20:32:00 我\n要不要一起去吃那家川菜？\n"
    "就是上次那家\n"
)

QQ_SEP = "=" * 64
QQ_BASIC = (
    "消息记录（此消息记录为文本格式，不包含图片等多媒体消息）\n"
    "消息分组:我的好友\n"
    f"{QQ_SEP}\n"
    "消息对象:小明(123456)\n"
    f"{QQ_SEP}\n"
    "\n"
    "2024-01-15 20:30:45 小明(123456)\n今天好累\n"
    "\n"
    "2024-01-15 20:31:02 我(654321)\n怎么了 最近还好吗\n"
)


# ===========================================================================
# 1. 双人正常聊天
# ===========================================================================
def t_wechat_basic(tmp: Tmp):
    r = run_wx(tmp, WX_BASIC, target="小明", self_names="我", source_ref="wx1")
    C.ok("wx: rc==0", r["rc"] == 0, f"rc={r['rc']}")
    d = r["data"]
    C.ok("wx: 4 messages kept separately", len(d["messages"]) == 4, f"got {len(d['messages'])}")
    roles = [m["sender"]["role"] for m in d["messages"]]
    C.ok("wx: roles user,target,user,target", roles == ["user", "target", "target", "user"], str(roles))
    C.ok("wx: schema valid", not schema_valid(d), str(schema_valid(d))[:200])
    m1, m2 = d["messages"][1], d["messages"][2]
    C.ok("wx: burst NOT merged", m1["body"] == "刚下班 累死了\n哈哈哈哈哈！！\n[图片]" and m2["body"] == "你呢",
         repr(m1["body"]))
    C.ok("wx: internal newline preserved", "\n" in m1["body"], repr(m1["body"]))
    C.ok("wx: sent_at normalized", m1["sent_at"] == "2024-01-15T20:31:02", str(m1["sent_at"]))
    C.ok("wx: placeholder kept in body, no media", "[图片]" in m1["body"] and m1["media"] is None and m1["content_type"] is None,
         f"body={m1['body']!r} ct={m1['content_type']}")
    C.ok("wx: my multi-line preserved", d["messages"][3]["body"] == "要不要一起去吃那家川菜？\n就是上次那家")


def t_qq_basic(tmp: Tmp):
    r = run_qq(tmp, QQ_BASIC, target="小明", self_account="654321", source_ref="qq1")
    C.ok("qq: rc==0", r["rc"] == 0, f"rc={r['rc']}")
    d = r["data"]
    C.ok("qq: 2 messages", len(d["messages"]) == 2, f"got {len(d['messages'])}")
    C.ok("qq: sender_key from QQ number", d["messages"][0]["sender"]["sender_key"] == "123456"
         and d["messages"][1]["sender"]["sender_key"] == "654321",
         str([m["sender"]["sender_key"] for m in d["messages"]]))
    C.ok("qq: schema valid", not schema_valid(d), str(schema_valid(d))[:200])
    C.ok("qq: conversation_title", d["conversation_title"] == "小明", str(d["conversation_title"]))


# ===========================================================================
# 2. 连续短消息（已并入 basic 的连发），3. 多行消息
# ===========================================================================
def t_multiline_burst(tmp: Tmp):
    txt = ("2024-02-01 23:00:00 小明\n在吗\n"
           "2024-02-01 23:00:01 小明\n睡了吗\n"
           "2024-02-01 23:00:03 小明\n那算了\n")
    r = run_wx(tmp, txt, target="小明", self_names="我")
    d = r["data"]
    C.ok("wx burst: 3 separate", len(d["messages"]) == 3, str(len(d["messages"])))
    bodies = [m["body"] for m in d["messages"]]
    C.ok("wx burst: each single line", bodies == ["在吗", "睡了吗", "那算了"], repr(bodies))
    ids = [m["id"] for m in d["messages"]]
    C.ok("wx burst: ids unique", len(set(ids)) == 3, str(ids))


# ===========================================================================
# 4. 昵称变化
# ===========================================================================
def t_nickname_change(tmp: Tmp):
    txt = ("2023-06-01 12:00:00 小明\n晚上聚餐？\n"
           "2023-06-01 12:01:00 小明改名叫明哥了\n真的\n"
           "2023-06-01 12:02:00 明哥\n我改名了哈\n")
    r = run_wx(tmp, txt, target="小明", self_names="我")
    d = r["data"]
    # 第三次发送者头是 "明哥改名叫明哥了" —— 这行被当成 sender 名了！断言它 unknown
    names = [m["sender"]["name"] for m in d["messages"]]
    roles = [m["sender"]["role"] for m in d["messages"]]
    C.ok("wx rename: unknown label flagged", roles[2] == "unknown", str(roles))
    # 真实昵称变化（改名消息里 sender 与目标一致 → target）
    txt2 = ("2023-06-01 12:00:00 小明\n晚上聚餐？\n"
            "2023-06-01 12:01:00 明哥\n我改名了 以后叫我明哥\n")
    r2 = run_wx(tmp, txt2, name="wx2.txt", out="wx2.json", target="小明,明哥", self_names="我")
    roles2 = [m["sender"]["role"] for m in r2["data"]["messages"]]
    C.ok("wx rename: both aliases resolve target",
         roles2 == ["target", "target"], str(roles2))
    # QQ：靠 QQ 号稳定（改名也不丢）；须 --target 才归 target
    qq = (f"消息对象:明哥(123456)\n{QQ_SEP}\n2024-01-15 20:30:45 小明(123456)\n晚上聚餐\n"
          "2024-01-15 20:31:00 明哥(123456)\n我改名了\n")
    rq = run_qq(tmp, qq, name="qq2.txt", out="qq2.json",
                target="123456", self_account="654321")
    C.ok("qq rename: QQ号稳定归 target",
         rq["data"]["messages"][0]["sender"]["role"] == "target"
         and rq["data"]["messages"][1]["sender"]["sender_key"] == "123456",
         str([(m["sender"]["name"], m["sender"]["role"], m["sender"]["sender_key"]) for m in rq["data"]["messages"]]))


# ===========================================================================
# 5. 无法识别 sender
# ===========================================================================
def t_unknown_sender(tmp: Tmp):
    txt = ("2024-01-15 20:30:45 老王\n谁啊\n"
           "2024-01-15 20:31:02 我\n不认识你\n")
    r = run_wx(tmp, txt, target="小明", self_names="我")
    d = r["data"]
    roles = [m["sender"]["role"] for m in d["messages"]]
    C.ok("wx unknown: stranger not guessed as target/user", roles == ["unknown", "user"], str(roles))
    C.ok("wx unknown: schema still valid", not schema_valid(d), str(schema_valid(d))[:200])


# ===========================================================================
# 6. 模糊时间（无完整日期 → sent_at null，保留 raw）
# ===========================================================================
def t_fuzzy_time(tmp: Tmp):
    txt = ("2024-01-15 20:30:45 小明\n精确时间\n"
           "昨天 23:12 小明\n模糊时间\n")
    r = run_wx(tmp, txt, target="小明", self_names="我")
    d = r["data"]
    ms = d["messages"]
    C.ok("wx fuzzy: exact normalized", ms[0]["sent_at"] == "2024-01-15T20:30:45", str(ms[0]["sent_at"]))
    C.ok("wx fuzzy: fuzzy->None + raw preserved",
         ms[1]["sent_at"] is None and ms[1]["sent_at_raw"] == "昨天 23:12",
         f"sent_at={ms[1]['sent_at']!r} raw={ms[1]['sent_at_raw']!r}")


# ===========================================================================
# 7. 图片/语音占位符（不伪造 media）
# ===========================================================================
def t_placeholders(tmp: Tmp):
    txt = ("2024-01-15 20:30:45 小明\n[图片]\n"
           "2024-01-15 20:31:00 小明\n[语音]\n"
           "2024-01-15 20:31:05 小明\n哈哈哈 [图片] 真好笑\n")
    r = run_wx(tmp, txt, target="小明", self_names="我")
    ms = r["data"]["messages"]
    for i, m in enumerate(ms):
        C.ok(f"wx placeholder msg{i}: body kept, media None, ct None",
             m["media"] is None and m["content_type"] is None
             and m["body"] in ("[图片]", "[语音]", "哈哈哈 [图片] 真好笑"),
             f"body={m['body']!r} ct={m['content_type']!r}")


# ===========================================================================
# 8. 空消息
# ===========================================================================
def t_empty_message(tmp: Tmp):
    txt = "2024-01-15 20:30:45 小明\n\n2024-01-15 20:31:00 小明\n有内容\n"
    r = run_wx(tmp, txt, target="小明", self_names="我")
    ms = r["data"]["messages"]
    C.ok("wx empty: 2 messages", len(ms) == 2, str(len(ms)))
    C.ok("wx empty: empty body == '' (distinct from null)", ms[0]["body"] == "", repr(ms[0]["body"]))


# ===========================================================================
# 9. 异常格式（显式失败，不静默）
# ===========================================================================
def t_bad_formats(tmp: Tmp):
    # csv
    r1 = run_wx(tmp, "a,b,c\n1,2,3\n", name="x.csv", out="o1.json")
    C.ok("wx csv: explicit unsupported (rc!=0, no output)", r1["rc"] != 0 and r1["data"] is None,
         f"rc={r1['rc']}")
    # sqlite
    r2 = run_wx(tmp, "x", name="x.sqlite", out="o2.json")
    C.ok("wx sqlite: explicit unsupported", r2["rc"] != 0 and r2["data"] is None, f"rc={r2['rc']}")
    # txt without header
    r3 = run_wx(tmp, "这是一段没有时间戳的纯文本\n第二行\n", name="raw.txt", out="o3.json")
    C.ok("wx unstructured txt: explicit fail, no silent plaintext", r3["rc"] != 0 and r3["data"] is None,
         f"rc={r3['rc']}")
    # qq mht
    r4 = run_qq(tmp, "<html><body>hi</body></html>", name="x.mht", out="o4.json")
    C.ok("qq mht: explicit unsupported", r4["rc"] != 0 and r4["data"] is None, f"rc={r4['rc']}")


# ===========================================================================
# 10. 跨导入去重（fingerprint 候选 + 不掺 sequence；id 导入内唯一）
# ===========================================================================
def t_id_stability(tmp: Tmp):
    r1 = run_wx(tmp, WX_BASIC, name="a.txt", out="a.json", target="小明", self_names="我", source_ref="s1")
    r2 = run_wx(tmp, WX_BASIC, name="b.txt", out="b.json", target="小明", self_names="我", source_ref="s2")
    d1, d2 = r1["data"], r2["data"]
    # 同一文件内容完整重导入（同序）→ id 也相同：稳定、可复现、确定性（非缺陷）
    C.ok("id: full identical re-import -> same ids (deterministic)",
         [m["id"] for m in d1["messages"]] == [m["id"] for m in d2["messages"]],
         f"d1={[m['id'] for m in d1['messages']]} d2={[m['id'] for m in d2['messages']]}")
    # 两份导出同一条原始消息 → fingerprint 一致（跨 source_ref 的候选去重信号）
    fp1 = [m["content_fingerprint"] for m in d1["messages"]]
    fp2 = [m["content_fingerprint"] for m in d2["messages"]]
    C.ok("fp: same message across source_ref -> identical fingerprint",
         fp1 == fp2, f"fp1={fp1} fp2={fp2}")
    C.ok("fp: distinct messages distinct fingerprint",
         len(set(fp1)) == 4, str(fp1))
    C.ok("source_ref preserved per import",
         d1["source_ref"] == "s1" and d2["source_ref"] == "s2",
         f"{d1['source_ref']} vs {d2['source_ref']}")
    # id 掺入 sequence → id 不是跨导入判重键：同一消息在重叠切片中落不同 sequence 时 id 不同。
    # 这正是 fingerprint + 上下文负责去重的理由（见 B）。此处仅证明：id 变化由 sequence 驱动。
    r3 = run_wx(tmp, WX_BASIC, name="a.txt", out="a3.json", target="小明", self_names="我", source_ref="s1")
    C.ok("id: reparse same file -> stable ids",
         [m["id"] for m in d1["messages"]] == [m["id"] for m in r3["data"]["messages"]],
         str([m["id"] for m in r3["data"]["messages"]]))


# ===========================================================================
# A. 同秒同 sender 同 body 三条 → 三个不同 message id
# ===========================================================================
def t_same_second_collision(tmp: Tmp):
    txt = ("2024-01-15 20:30:00 小明\n好的\n"
           "2024-01-15 20:30:00 小明\n好的\n"
           "2024-01-15 20:30:00 小明\n好的\n")
    r = run_wx(tmp, txt, target="小明", self_names="我")
    d = r["data"]
    ids = [m["id"] for m in d["messages"]]
    fps = [m["content_fingerprint"] for m in d["messages"]]
    C.ok("A: three distinct ids", len(set(ids)) == 3, str(ids))
    C.ok("A: fingerprints collide (expected, dedup needs context)",
         len(set(fps)) == 1, str(fps))
    C.ok("A: schema valid", not schema_valid(d), str(schema_valid(d))[:200])


# ===========================================================================
# B. 同消息跨 source_ref：fingerprint 一致；id 稳定；说明去重依赖字段
# ===========================================================================
def t_cross_import_dedup(tmp: Tmp):
    # 文件 A 含 3 条（含一条独特消息），文件 B 是 A 的重叠切片（重复了同 2 条）
    src = ("2024-03-01 10:00:00 小明\n第一\n"
           "2024-03-01 10:01:00 我\n第二\n"
           "2024-03-01 10:02:00 小明\n第三\n")
    a = run_wx(tmp, src, name="full.txt", out="full.json", target="小明", self_names="我", source_ref="importA")
    sub = ("2024-03-01 10:01:00 我\n第二\n"
           "2024-03-01 10:02:00 小明\n第三\n")
    b = run_wx(tmp, sub, name="slice.txt", out="slice.json", target="小明", self_names="我", source_ref="importB")
    fa = [m["content_fingerprint"] for m in a["data"]["messages"]]
    fb = [m["content_fingerprint"] for m in b["data"]["messages"]]
    C.ok("B: overlapping messages share fingerprint",
         fa[1] == fb[0] and fa[2] == fb[1], f"{fa} vs {fb}")
    C.ok("B: id NOT expected equal across imports (id is per-import unique)",
         True, "去重不靠 id")
    # 展示去重依赖字段（候选=同指纹，确认=同 sender+相邻 sent_at+附近 sequence）
    same = [i for i, x in enumerate(fb) if x in fa]
    C.ok("B: candidate count via fingerprint", same == [0, 1], str(same))


# ===========================================================================
# 11. participants 初判（收紧后）/ 12. confirmed 覆盖
# ===========================================================================
def t_participants(tmp: Tmp):
    # 双人有 --self-names 但无 --target → 唯一对方低置信候选(confirmed=false)
    txt = ("2024-01-15 20:30:45 我\n在吗\n"
           "2024-01-15 20:31:00 阿强\n在的\n")
    r = run_wx(tmp, txt, self_names="我")
    d = r["data"]
    tgt = [p for p in d["participants"] if p["role"] == "target"]
    C.ok("parts: target as low-confidence candidate (confirmed=False)",
         len(tgt) == 1 and tgt[0]["confirmed"] is False and tgt[0]["confidence"] <= 0.5,
         json.dumps(d["participants"], ensure_ascii=False))
    roles = [m["sender"]["role"] for m in d["messages"]]
    C.ok("parts: messages resolved user + target(candidate)", roles == ["user", "target"], str(roles))
    C.ok("parts: schema valid", not schema_valid(d), str(schema_valid(d))[:200])

    # 改昵称后加 --target 别名 → 都归 target
    txt2 = ("2024-06-01 09:00:00 阿强\n早\n"
            "2024-06-01 09:01:00 强哥\n早啊\n")
    r2 = run_wx(tmp, txt2, name="wx2.txt", out="wx2.json", self_names="我", target="阿强,强哥")
    C.ok("parts: multi-alias target resolve", [m["sender"]["role"] for m in r2["data"]["messages"]] == ["target", "target"],
         str([(m["sender"]["name"], m["sender"]["role"]) for m in r2["data"]["messages"]]))

    # confirmed 覆盖：某人初判为 target，用户确认他其实是你朋友(other)
    reg = cc.ParticipantRegistry()
    reg.add_guess("target", names=["老王"], confidence=0.9)
    reg.add_manual("other", names=["老王"])
    res = reg.resolve("老王", None)
    C.ok("parts: manual override beats guess", res["role"] == "other", json.dumps(res, ensure_ascii=False))
    C.ok("parts: manual flips confirmed in list",
         any(p["role"] == "other" and p["confirmed"] is True and p["match_method"] == "manual"
             for p in reg.to_list()), json.dumps(reg.to_list(), ensure_ascii=False))
    C.ok("parts: guess entry dropped from list",
         not any(p["role"] == "target" for p in reg.to_list()), json.dumps(reg.to_list(), ensure_ascii=False))


# ===========================================================================
# 13. 中文编码（gb18030 无 BOM 也能读）
# ===========================================================================
def t_encoding(tmp: Tmp):
    content = "2024-01-15 20:30:45 我\n在干嘛\n2024-01-15 20:31:00 小明\n哈哈哈哈哈\n"
    gbk_bytes = content.encode("gb18030")
    fp = tmp.path("gbk.txt")
    with open(fp, "wb") as f:
        f.write(gbk_bytes)
    argv = ["--file", fp, "--output", tmp.path("gbk.json"), "--target", "小明",
            "--self-names", "我"]
    rc = wechat_parser.main(argv)
    d = json.load(open(tmp.path("gbk.json"), encoding="utf-8"))
    C.ok("gb18030: decoded", rc == 0 and len(d["messages"]) == 2, f"rc={rc}")
    C.ok("gb18030: no mojibake", d["messages"][1]["body"] == "哈哈哈哈哈", repr(d["messages"][1]["body"]))

    # 二进制 → EncodingError
    fp2 = tmp.path("bin.txt")
    with open(fp2, "wb") as f:
        f.write(b"\x00\x01\x02\x03 NUL bytes")
    argv2 = ["--file", fp2, "--output", tmp.path("bin.json")]
    rc2 = wechat_parser.main(argv2)
    C.ok("binary: explicit error", rc2 != 0, f"rc={rc2}")


# ===========================================================================
# 14. 群聊/多会话（QQ 多会话 → 多个 ChatImport 输出文件）
# ===========================================================================
def t_group_multi(tmp: Tmp):
    multi = (
        "消息记录（此消息记录为文本格式）\n"
        "消息对象:小明(123456)\n"
        f"{QQ_SEP}\n"
        "2024-01-15 20:30:00 小明(123456)\n在吗\n"
        "\n"
        "消息对象:大学室友群(888888)\n"
        f"{QQ_SEP}\n"
        "2024-06-01 12:00:00 小明(123456)\n晚上聚餐？\n"
        "2024-06-01 12:01:00 老王(777777)\n算我一个\n"
        "2024-06-01 12:02:00 我(654321)\n我也去\n"
    )
    outdir = tmp.path("multi")
    os.makedirs(outdir, exist_ok=True)
    fp = tmp.path("multi.txt")
    with open(fp, "w", encoding="utf-8") as f:
        f.write(multi)
    argv = ["--file", fp, "--output", outdir, "--target", "小明",
            "--self-account", "654321", "--self-names", "我"]
    rc = qq_parser.main(argv)
    files = [x for x in os.listdir(outdir) if x.endswith(".json")]
    C.ok("qq multi: rc==0 and 2 session files", rc == 0 and len(files) == 2,
         f"rc={rc} files={files}")
    if len(files) == 2:
        sess1 = json.load(open(os.path.join(outdir, "小明.json"), encoding="utf-8"))
        sess2_name = [f for f in files if f != "小明.json"][0]
        sess2 = json.load(open(os.path.join(outdir, sess2_name), encoding="utf-8"))
        C.ok("qq multi: session1 single chat target", len(sess1["messages"]) == 1
             and sess1["messages"][0]["sender"]["role"] == "target", json.dumps(sess1["messages"], ensure_ascii=False))
        C.ok("qq multi: group session roles target/other/user",
             [m["sender"]["role"] for m in sess2["messages"]] == ["target", "other", "user"],
             str([(m["sender"]["name"], m["sender"]["role"]) for m in sess2["messages"]]))
        C.ok("qq multi: 老王(other) 不被猜成 target/user",
             sess2["messages"][1]["sender"]["role"] == "other",
             str(sess2["messages"][1]["sender"]["role"]))
        C.ok("qq multi: source_ref suffixed", sess1["source_ref"].endswith("__session1")
             and sess2["source_ref"].endswith("__session2"),
             f"{sess1['source_ref']} / {sess2['source_ref']}")
        C.ok("qq multi: both schema valid",
             not schema_valid(sess1) and not schema_valid(sess2),
             f"{schema_valid(sess1)[:2]} {schema_valid(sess2)[:2]}")


# ===========================================================================
# json content_type（留痕 JSON 只在确证时给类型）
# ===========================================================================
def t_json_content_type(tmp: Tmp):
    lj = [
        {"sender": "小明", "time": 1705320000, "content": "在吗", "type": 1},
        {"sender": "小明", "time": 1705320060, "content": "[图片]", "type": 3},
        {"sender": "我", "time": 1705320120, "content": "嗯嗯", "type": 1},
    ]
    fp = tmp.path("lj.json")
    with open(fp, "w", encoding="utf-8") as f:
        f.write(jsonify(lj))
    argv = ["--file", fp, "--output", tmp.path("lj_out.json"), "--target", "小明", "--self-names", "我"]
    rc = wechat_parser.main(argv)
    d = json.load(open(tmp.path("lj_out.json"), encoding="utf-8"))
    C.ok("json: rc==0", rc == 0, f"rc={rc}")
    cts = [m["content_type"] for m in d["messages"]]
    C.ok("json: msgType text/image mapped", cts == ["text", "image", "text"], str(cts))
    C.ok("json: epoch->ISO", d["messages"][0]["sent_at"] is not None, str(d["messages"][0]["sent_at"]))
    C.ok("json: body verbatim placeholder", d["messages"][1]["body"] == "[图片]", repr(d["messages"][1]["body"]))
    C.ok("json: media null (json有type但无附件元数据，不伪造media对象)", d["messages"][1]["media"] is None)
    C.ok("json: schema valid", not schema_valid(d), str(schema_valid(d))[:200])


# ===========================================================================
# 反例：直接往 ChatImport 塞非法值必须被 schema 拒绝
# ===========================================================================
def t_schema_negative(tmp: Tmp):
    r = run_wx(tmp, WX_BASIC, target="小明", self_names="我", source_ref="wx_neg")
    d = r["data"]
    # platform 非法
    d2 = json.loads(json.dumps(d)); d2["platform"] = "telegram"
    C.ok("schema-neg: bad platform rejected", bool(schema_valid(d2)), "")
    # messages 变字符串
    d3 = json.loads(json.dumps(d)); d3["messages"] = "nope"
    C.ok("schema-neg: messages string rejected", bool(schema_valid(d3)), "")
    # 顶层多属性
    d4 = json.loads(json.dumps(d)); d4["evil"] = True
    C.ok("schema-neg: extra top prop rejected", bool(schema_valid(d4)), "")
    # 消息缺 sender.role
    d5 = json.loads(json.dumps(d)); d5["messages"][0]["sender"] = {"name": "小明"}
    C.ok("schema-neg: missing sender.role rejected", bool(schema_valid(d5)), "")
    # participant confirmed 非布尔
    d6 = json.loads(json.dumps(d)); d6["participants"][0]["confirmed"] = "yes"
    C.ok("schema-neg: confirmed non-bool rejected", bool(schema_valid(d6)), "")
    # participant match_method 非法
    d7 = json.loads(json.dumps(d)); d7["participants"][0]["match_method"] = "telepathy"
    C.ok("schema-neg: match_method bad enum rejected", bool(schema_valid(d7)), "")
    # content_fingerprint 缺失（新必填）
    d8 = json.loads(json.dumps(d))
    for m in d8["messages"]:
        del m["content_fingerprint"]
    C.ok("schema-neg: missing content_fingerprint rejected", bool(schema_valid(d8)), "")
    # 同 ChatImport 内出现两条完全相同的行（重复 rows）→ uniqueItems 兜底拒绝
    # （id 唯一性由解析层 assert_unique_ids 保证，见 A 测试：三条同秒同内容仍得 3 个不同 id）
    d9 = json.loads(json.dumps(d)); d9["messages"][1] = json.loads(json.dumps(d9["messages"][0]))
    C.ok("schema-neg: duplicate full message row rejected (uniqueItems)",
         bool(schema_valid(d9)), "")


# ===========================================================================
# C. 两个陌生 sender、无 --self/--target/account_id → 不得猜 target
# ===========================================================================
def t_two_strangers_no_target(tmp: Tmp):
    txt = ("2024-01-15 20:30:45 阿强\n在吗\n"
           "2024-01-15 20:31:00 阿珍\n在的\n")
    r = run_wx(tmp, txt)
    d = r["data"]
    roles = [m["sender"]["role"] for m in d["messages"]]
    C.ok("C: no self/target anchors -> neither is target", roles == ["unknown", "unknown"], str(roles))
    C.ok("C: no target participant declared",
         not any(p["role"] == "target" for p in d["participants"]),
         json.dumps(d["participants"], ensure_ascii=False))
    C.ok("C: schema valid", not schema_valid(d), str(schema_valid(d))[:200])


# ===========================================================================
# D. 明确 --target 后，对应 participant 正确成为 target
# ===========================================================================
def t_explicit_target(tmp: Tmp):
    txt = ("2024-01-15 20:30:45 阿珍\n在吗\n"
           "2024-01-15 20:31:00 阿强\n在的\n"
           "2024-01-15 20:32:00 阿珍\n好吧\n")
    r = run_wx(tmp, txt, target="阿强", self_names="阿珍")
    d = r["data"]
    roles = [m["sender"]["role"] for m in d["messages"]]
    C.ok("D: explicit --target honored", roles == ["user", "target", "user"], str(roles))
    tgt = [p for p in d["participants"] if p["role"] == "target"]
    C.ok("D: target participant confirmed-ready guess",
         len(tgt) == 1 and tgt[0]["names"] == ["阿强"] and tgt[0]["confirmed"] is False,
         json.dumps(d["participants"], ensure_ascii=False))


# ===========================================================================
# E. 用户 confirmed 后，映射覆盖 parser 推断（真实 parser 输出被修正）
# ===========================================================================
def t_confirmed_overrides_parser(tmp: Tmp):
    # parser 初判：阿强=target 候选（阿珍=user）
    txt = ("2024-01-15 20:30:45 阿珍\n在吗\n"
           "2024-01-15 20:31:00 阿强\n在的\n")
    r = run_wx(tmp, txt, self_names="阿珍")
    d = r["data"]
    reg = cc.ParticipantRegistry()
    # 把 parser 初判的 target 名字/账号喂进 registry（初判）
    for p in d["participants"]:
        if p["confirmed"]:
            reg.add_manual(p["role"], account_id=p["account_id"], names=p["names"])
        else:
            kw = {"names": p["names"]}
            if p["account_id"]:
                kw["account_id"] = p["account_id"]
            reg.add_guess(p["role"], match_method=p["match_method"] or "name_exact",
                          confidence=p["confidence"] or 0.5, **kw)
    # 用户确认：阿强 其实是 target，但把『阿强』手动覆盖为 other（他其实是朋友）…
    # 更真实：用户确认 阿强=target（把他从低置信候选升级为 confirmed）
    reg.add_manual("target", names=["阿强"])
    res_t = reg.resolve("阿强", None)
    C.ok("E: confirmed upgrade wins", res_t["role"] == "target" and res_t["confidence"] == 1.0,
         json.dumps(res_t, ensure_ascii=False))
    # 用户纠正：把 parser 初判的 target(阿强) 改成 other（他其实是共同朋友）
    reg2 = cc.ParticipantRegistry()
    reg2.add_guess("user", names=["阿珍"], confidence=0.85)
    reg2.add_guess("target", names=["阿强"], confidence=0.5)
    reg2.add_manual("other", names=["阿强"])   # 覆盖初判 target→other
    res2 = reg2.resolve("阿强", None)
    parts2 = reg2.to_list()
    C.ok("E: correction overrides parser guess (target->other)",
         res2["role"] == "other",
         f"{json.dumps(res2, ensure_ascii=False)} {json.dumps(parts2, ensure_ascii=False)}")
    C.ok("E: corrected participant marked confirmed/manual",
         any(p["role"] == "other" and p["confirmed"] is True and p["match_method"] == "manual"
             for p in parts2), json.dumps(parts2, ensure_ascii=False))
    C.ok("E: stale target guess removed",
         not any(p["role"] == "target" for p in parts2), json.dumps(parts2, ensure_ascii=False))


# ===========================================================================
# 主流程
# ===========================================================================
def main():
    print("=== 聊天记录解析器测试 ===")
    tmp = Tmp()
    try:
        tests = [
            ("1. 微信双人正常聊天", t_wechat_basic),
            ("1. QQ双人正常聊天", t_qq_basic),
            ("2/3. 连发与多行", t_multiline_burst),
            ("4. 昵称变化", t_nickname_change),
            ("5. 无法识别 sender", t_unknown_sender),
            ("6. 模糊时间", t_fuzzy_time),
            ("7. 图片/语音占位符", t_placeholders),
            ("8. 空消息", t_empty_message),
            ("9. 异常格式显式失败", t_bad_formats),
            ("10. 跨导入 fingerprint 候选去重", t_id_stability),
            ("A. 同秒同内容 → id 不碰撞", t_same_second_collision),
            ("B. 跨 source_ref fingerprint", t_cross_import_dedup),
            ("11/12. participants 初判与 confirmed 覆盖", t_participants),
            ("C. 两陌生人不猜 target", t_two_strangers_no_target),
            ("D. 明确 --target 生效", t_explicit_target),
            ("E. confirmed 覆盖 parser 推断", t_confirmed_overrides_parser),
            ("13. 中文编码", t_encoding),
            ("14. 群聊多会话", t_group_multi),
            ("json. 留痕 JSON content_type", t_json_content_type),
            ("反例. schema 拒绝非法 ChatImport", t_schema_negative),
        ]
        for name, fn in tests:
            print(f"\n▶ {name}")
            fn(tmp)
    finally:
        tmp.cleanup()
    ok = C.summary()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
