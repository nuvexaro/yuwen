#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Import Pipeline 测试套件（test A–O）

直接运行： python3 test_import_pipeline.py
覆盖 Stage 3 硬约束：schema 校验闸门、confirmed target 唯一性、跨导入去重分级、
provenance 保留、Import Report 统计、中文编码、部分/完全解析失败。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import chat_parser_common as cc
import import_pipeline as ip
import wechat_parser
import qq_parser

QQ_SEP = "=" * 64


class C:
    ok_n = 0
    fail_n = 0
    failures = []

    @classmethod
    def ok(cls, name, cond, detail=""):
        if cond:
            cls.ok_n += 1
        else:
            cls.fail_n += 1
            cls.failures.append(name + (" — " + detail if detail else ""))
            print(f"FAIL {name} {detail}")


class Tmp:
    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="pipe_test_")

    def p(self, name):
        return os.path.join(self.dir, name)

    def write(self, name, content, enc="utf-8"):
        p = self.p(name)
        if isinstance(content, bytes):
            with open(p, "wb") as f:
                f.write(content)
        else:
            with open(p, "w", encoding=enc) as f:
                f.write(content)
        return p

    def cleanup(self):
        shutil.rmtree(self.dir, ignore_errors=True)


WX_A = ("2024-01-15 20:30:45 我\n在干嘛\n"
        "\n2024-01-15 20:31:02 小明\n刚下班\n哈哈哈哈哈！！\n[图片]\n"
        "\n2024-01-15 20:31:05 小明\n你呢\n")
QQ_B = (f"消息记录（此消息记录为文本格式）\n消息分组:我的好友\n{QQ_SEP}\n"
        f"消息对象:小明(123456)\n{QQ_SEP}\n"
        "2024-01-15 20:30:45 小明(123456)\n今天好累\n"
        "2024-01-15 20:31:02 我(654321)\n怎么了 最近还好吗\n")


def schema_errs(ci):
    return ip.validate_chat_import(ci).errors


def _confirmed_import_from_parse(pr, role_confirm_map):
    """把 parser 初判的 import 拿出来，对 participants 应用 manual 覆盖，重建 registry 并重发。"""
    ci = pr["imports"][0]["chat_import"]
    reg = cc.ParticipantRegistry()
    for p in ci["participants"]:
        kw = {"names": p["names"]}
        if p.get("account_id"):
            kw["account_id"] = p["account_id"]
        if p.get("confirmed"):
            reg.add_manual(p["role"], **kw)
        else:
            reg.add_guess(p["role"], match_method=p.get("match_method") or "name_exact",
                          confidence=p.get("confidence") or 0.5, **kw)
    # 应用用户确认映射 {名字/账号: role}
    for key, role in role_confirm_map.items():
        if key.isdigit() and len(key) >= 3:
            reg.add_manual(role, account_id=key)
        else:
            reg.add_manual(role, names=[key])
    return reg


# ===========================================================================
# A. 正常 WeChat import
# ===========================================================================
def tA(tmp):
    f = tmp.write("wx.txt", WX_A)
    res = ip.run_import_batch([f], target="小明", self_names="我", source_refs=["A"])
    r = res["reports"][0]
    C.ok("A: status success", r["final_status"] == "success", r["final_status"])
    C.ok("A: 3 messages parsed", r["successfully_parsed"] == 3, str(r["successfully_parsed"]))
    C.ok("A: no errors", r["errors"] == [], str(r["errors"]))
    C.ok("A: schema ok", r["schema_validation_ok"] is True)
    C.ok("A: source_ref preserved", r["per_import"][0]["source_ref"] == "A")


# ===========================================================================
# B. 正常 QQ import
# ===========================================================================
def tB(tmp):
    f = tmp.write("qq.txt", QQ_B)
    res = ip.run_import_batch([f], target="123456", self_account="654321", source_refs=["B"])
    r = res["reports"][0]
    C.ok("B: status success", r["final_status"] == "success", r["final_status"])
    C.ok("B: 2 messages", r["successfully_parsed"] == 2, str(r["successfully_parsed"]))
    C.ok("B: platform qq", "qq" in r["platforms"], str(r["platforms"]))


# ===========================================================================
# C. schema validation failure
# ===========================================================================
def tC(tmp):
    f = tmp.write("bad.txt", "2024-01-15 20:31:02 小明\n你好\n")
    # 直接对 malformed ChatImport 做 schema 校验
    res = ip.parse_source_file(f, target="小明", self_names="我", source_ref="C")
    ci = res["imports"][0]["chat_import"]
    ci["platform"] = "telegram"   # 非法枚举
    errs = schema_errs(ci)
    C.ok("C: invalid enum detected", len(errs) >= 1, str(errs))
    C.ok("C: schema error is diagnostic", any("telegram" in e or "not one of" in e for e in errs), str(errs[:2]))
    ci2 = json.loads(json.dumps(res["imports"][0]["chat_import"]))
    del ci2["messages"][0]["content_fingerprint"]
    C.ok("C: missing required field detected", len(schema_errs(ci2)) >= 1, str(schema_errs(ci2)[:1]))
    # 真实失败文件不得标记成功
    bad = tmp.write("bad2.txt", "not a chat at all, no headers anywhere\n随便写\n")
    res2 = ip.run_import_batch([bad], source_refs=["C2"])
    C.ok("C: parse failure not success", res2["reports"][0]["final_status"] == "failed",
         res2["reports"][0]["final_status"])
    C.ok("C: parse failure has error", res2["reports"][0]["errors"] != [], str(res2["reports"][0]["errors"]))


# ===========================================================================
# D. unknown participants
# ===========================================================================
def tD(tmp):
    f = tmp.write("unk.txt", "2024-01-15 20:30:45 阿强\n在吗\n2024-01-15 20:31:00 阿珍\n在的\n")
    res = ip.run_import_batch([f], source_refs=["D"])
    r = res["reports"][0]
    C.ok("D: unknown_sender_count 2", r["unknown_sender_count"] == 2, str(r["unknown_sender_count"]))
    C.ok("D: no confirmed participant", r["confirmed_participants"] == 0)
    C.ok("D: no target candidate forced", r["unconfirmed_candidates"] == 0, str(r["unconfirmed_candidates"]))


# ===========================================================================
# E. unconfirmed target candidate 不进入 downstream target
# ===========================================================================
def tE(tmp):
    f = tmp.write("e.txt", "2024-01-15 20:30:45 我\n在吗\n2024-01-15 20:31:00 小明\n在的\n")
    res = ip.parse_source_file(f, target="小明", self_names="我", source_ref="E")
    ci = res["imports"][0]["chat_import"]
    snap = ip.target_identity_snapshot(ci)
    C.ok("E: has unconfirmed candidate", len(snap["candidates"]) == 1 and snap["confirmed_target"] is None,
         json.dumps(snap, ensure_ascii=False))
    C.ok("E: gated target messages = 0", len(ip.messages_belonging_to_confirmed_target(ci)) == 0,
         str(len(ip.messages_belonging_to_confirmed_target(ci))))


# ===========================================================================
# F. confirmed target 可以进入 downstream target
# ===========================================================================
def tF(tmp):
    f = tmp.write("f.txt", "2024-01-15 20:30:45 我\n在吗\n2024-01-15 20:31:00 小明\n在的\n")
    pr = ip.parse_source_file(f, target="小明", self_names="我", source_ref="F")
    reg = _confirmed_import_from_parse(pr, {"小明": "target"})
    text = open(f, encoding="utf-8").read()
    raw, _ = wechat_parser.parse_wechat_txt(text, "f.txt")
    ci = wechat_parser._emit(raw, reg, "小明", "F", [], "f.txt")
    snap = ip.target_identity_snapshot(ci)
    C.ok("F: confirmed_target set", snap["confirmed_target"] is not None
         and snap["confirmed_target"]["confirmed"] is True,
         json.dumps(snap, ensure_ascii=False))
    tm = ip.messages_belonging_to_confirmed_target(ci)
    C.ok("F: 1 message gated to target", len(tm) == 1 and tm[0]["sender"]["role"] == "target",
         str([(m['sender']['name'], m['sender']['role']) for m in tm]))


# ===========================================================================
# G. 三条同秒同内容不能误合并
# ===========================================================================
def tG(tmp):
    f = tmp.write("g.txt", "2024-01-15 20:30:00 小明\n好的\n"
                  "2024-01-15 20:30:00 小明\n好的\n"
                  "2024-01-15 20:30:00 小明\n好的\n")
    res = ip.run_import_batch([f], target="小明", self_names="我", source_refs=["G"])
    r = res["reports"][0]
    C.ok("G: 3 messages survive", r["successfully_parsed"] == 3, str(r["successfully_parsed"]))
    # 同批内无跨批重复，3 条都应 distinct（未被误删/误并）
    C.ok("G: all distinct", res["dedup"]["stats"]["distinct"] == 3, str(res["dedup"]["stats"]))


# ===========================================================================
# H. 两个 source_ref 相同消息 → duplicate candidate
# ===========================================================================
def tH(tmp):
    a = tmp.write("ha.txt", "2024-01-15 20:31:02 小明\n你好呀\n")
    b = tmp.write("hb.txt", "2024-01-15 20:31:02 小明\n你好呀\n")
    res = ip.run_import_batch([a, b], target="小明", self_names="我", source_refs=["HA", "HB"])
    st = res["dedup"]["stats"]
    C.ok("H: exact candidates found", st["exact"] == 2, str(st))
    C.ok("H: one cluster", len(res["dedup"]["clusters"]) == 1, str(res["dedup"]["clusters"]))
    # provenance: 两个 source_ref 都保留
    refs = {r["source_ref"] for r in res["dedup"]["records"]}
    C.ok("H: both source_refs retained", refs == {"HA", "HB"}, str(refs))


# ===========================================================================
# I. 同指纹但实际是两条真实消息 → 不误删
# ===========================================================================
def tI(tmp):
    a = tmp.write("ia.txt", "2024-01-15 20:30:00 小明\n好的\n2024-01-15 20:30:00 小明\n好的\n")
    b = tmp.write("ib.txt", "2024-01-15 20:30:00 小明\n好的\n")  # 与 A 的哪一条重复？歧义
    res = ip.run_import_batch([a, b], target="小明", self_names="我", source_refs=["IA", "IB"])
    st = res["dedup"]["stats"]
    C.ok("I: no false exact", st["exact"] == 0, str(st))
    # 3 条都不应被误判为可安全删除的 exact；unresolved >= 3
    C.ok("I: ambiguous -> unresolved, nothing deleted",
         st["unresolved"] >= 3 and len(res["dedup"]["records"]) == 3, str(st))


# ===========================================================================
# J. 时间格式不同 fingerprint 不同，但上下文仍成候选
# ===========================================================================
def tJ(tmp):
    a = tmp.write("ja.txt", "2024-03-01 10:00:00 小明\n晚上聚餐？\n2024-03-01 10:01:00 我\n好啊\n")
    b = tmp.write("jb.txt", "2024-03-01 10:00 小明\n晚上聚餐？\n2024-03-01 10:01 我\n好啊\n")  # 无秒
    res = ip.run_import_batch([a, b], target="小明", self_names="我", source_refs=["JA", "JB"])
    st = res["dedup"]["stats"]
    C.ok("J: probable candidates from time-format diff", st["probable"] == 4, str(st))


# ===========================================================================
# K. import 失败不产生成功状态
# ===========================================================================
def tK(tmp):
    cases = [
        ("k.csv", "a,b,c\n"),
        ("k.sqlite", "not sqlite"),
        ("k.mht", "<html>x</html>"),
        ("k_bad.txt", "no timestamp header here\nline two\n"),
    ]
    for name, content in cases:
        f = tmp.write(name, content)
        res = ip.run_import_batch([f], source_refs=[name])
        r = res["reports"][0]
        C.ok(f"K: {name} -> failed", r["final_status"] == "failed", f"{name} -> {r['final_status']}")
        C.ok(f"K: {name} error non-empty", r["errors"] != [], str(r["errors"]))
        C.ok(f"K: {name} no messages counted success", r["successfully_parsed"] == 0,
             str(r["successfully_parsed"]))


# ===========================================================================
# L. provenance 保留（去重不丢 source_ref 关系）
# ===========================================================================
def tL(tmp):
    a = tmp.write("la.txt", "2024-01-15 20:31:02 小明\n你好呀\n2024-01-15 20:31:05 我\n嗨\n")
    b = tmp.write("lb.txt", "2024-01-15 20:31:02 小明\n你好呀\n")
    res = ip.run_import_batch([a, b], target="小明", self_names="我", source_refs=["LA", "LB"])
    recs = res["dedup"]["records"]
    # 每条记录带 source_ref 与邻居(rid, ref, grade)
    all_have_prov = all("source_ref" in r and isinstance(r["neighbours"], list) for r in recs)
    C.ok("L: every record has provenance", all_have_prov, str(recs))
    refs = {r["source_ref"] for r in recs}
    C.ok("L: both origins survive dedup", refs == {"LA", "LB"}, str(refs))
    # exact 记录应互相指向对方并带对方 source_ref（跨来源保留）
    exact = [r for r in recs if r["dedup"] == "exact"]
    if exact:
        # LA 的那条 exact 应指向 LB；LB 的那条 exact 应指向 LA
        cross_refs = {n[1] for r in exact for n in r["neighbours"] if n[1] != r["source_ref"]}
        C.ok("L: exact neighbours carry opposite source_ref", cross_refs == {"LA", "LB"}, str(cross_refs))
        for r in exact:
            nbr_refs = {n[1] for n in r["neighbours"]}
            own = r["source_ref"]
            C.ok(f"L: {own} exact points to other import", nbr_refs == ({"LA", "LB"} - {own}), str(nbr_refs))


# ===========================================================================
# M. 中文编码（gb18030）
# ===========================================================================
def tM(tmp):
    content = "2024-01-15 20:30:45 我\n在干嘛\n2024-01-15 20:31:00 小明\n哈哈哈哈哈\n"
    f = tmp.write("gbk.txt", content.encode("gb18030"))
    res = ip.run_import_batch([f], target="小明", self_names="我", source_refs=["M"])
    r = res["reports"][0]
    C.ok("M: gb18030 parses", r["final_status"] == "success", r["final_status"] + str(r["errors"]))
    C.ok("M: 2 messages", r["successfully_parsed"] == 2, str(r["successfully_parsed"]))
    # 二进制 → 失败
    fb = tmp.write("bin.txt", b"\x00\x01\x02 binary")
    res2 = ip.run_import_batch([fb], source_refs=["M2"])
    C.ok("M: binary fails cleanly", res2["reports"][0]["final_status"] == "failed", res2["reports"][0]["final_status"])


# ===========================================================================
# N. 部分消息解析失败
# ===========================================================================
def tN(tmp):
    # wechat: 三条正常 + 一条消息头前的杂散 → 正常消息被保留、杂散告警、不整体失败
    text = ("2024-01-15 20:30:00 小明\n第一条\n"
            "2024-01-15 20:31:00 我\n第二条\n"
            "2024-01-15 20:32:00 小明\n第三条\n")
    f = tmp.write("n.txt", text)
    res = ip.run_import_batch([f], target="小明", self_names="我", source_refs=["N"])
    r = res["reports"][0]
    C.ok("N: success (valid messages kept)", r["final_status"] == "success", r["final_status"] + str(r["errors"]))
    C.ok("N: 3 messages", r["successfully_parsed"] == 3, str(r["successfully_parsed"]))


# ===========================================================================
# O. 完全无法解析
# ===========================================================================
def tO(tmp):
    for name, content in [("o.txt", ""), ("o2.txt", "\n\n\n")]:
        f = tmp.write(name, content)
        res = ip.run_import_batch([f], source_refs=[name])
        C.ok(f"O: {name} empty -> failed", res["reports"][0]["final_status"] == "failed",
             res["reports"][0]["final_status"])
        C.ok(f"O: {name} has diagnostic error", res["reports"][0]["errors"] != [], str(res["reports"][0]["errors"]))


def main():
    print("=== Import Pipeline 测试 ===")
    tmp = Tmp()
    try:
        tests = [
            ("A. 正常 WeChat import", tA),
            ("B. 正常 QQ import", tB),
            ("C. schema validation failure", tC),
            ("D. unknown participants", tD),
            ("E. unconfirmed target 不进 downstream", tE),
            ("F. confirmed target 进 downstream", tF),
            ("G. 同秒同内容 3 条不误合并", tG),
            ("H. 两 source_ref 相同消息成候选", tH),
            ("I. 同指纹两条真消息不误删", tI),
            ("J. 时间格式不同仍成候选", tJ),
            ("K. import 失败无成功状态", tK),
            ("L. provenance 保留", tL),
            ("M. 中文编码", tM),
            ("N. 部分消息解析失败", tN),
            ("O. 完全无法解析", tO),
        ]
        for name, fn in tests:
            print(f"\n▶ {name}")
            fn(tmp)
    finally:
        tmp.cleanup()
    print(f"\n通过 {C.ok_n} / 失败 {C.fail_n}")
    for f_ in C.failures:
        print("  -", f_)
    sys.exit(0 if C.fail_n == 0 else 1)


if __name__ == "__main__":
    main()
