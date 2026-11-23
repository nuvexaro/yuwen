#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""纠正跨会话召回回归测试（v0.3.0）。

背景：曾有报告认为"纠正写盘成功但重启后召回不到"。经核查，当时失败观测是绕过
persona_loader 直接 retrieve() 导致的误判；产品真实路径一直通过 loader 投影。

本测试用 production_host.Host 走完整路径，锁住这一点：
  导入示例 → 纠正 → 确认写回 → 新建 Host + 新会话 → 追问
并额外断言 loader 本身的输出已含投影，防止未来有人断开接线。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for _p in (ROOT, os.path.join(ROOT, "tools"), os.path.join(ROOT, "runtime"),
           os.path.join(ROOT, "stage6", "host"), os.path.join(ROOT, "evaluation")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from production_host import Host  # noqa: E402
import eval_runner as er  # noqa: E402
import skill_writer_v12 as sw  # noqa: E402
import memory_retrieval as mr  # noqa: E402
import context_assembly as ca  # noqa: E402
import persona_loader as pl  # noqa: E402


class C:
    ok_n = 0
    fail_n = 0
    fails = []

    @classmethod
    def ok(cls, name, cond, detail=""):
        if cond:
            cls.ok_n += 1
        else:
            cls.fail_n += 1
            cls.fails.append(name + (f" — {detail}" if detail else ""))
            print(f"FAIL {name} {detail}")


def t_recall_after_restart():
    tmp = tempfile.mkdtemp(prefix="ex_recall_")
    try:
        base = os.path.join(tmp, "exes")
        sessions = os.path.join(tmp, "sessions")
        chat = json.load(open(os.path.join(ROOT, "evaluation", "dataset", "case_001", "messages.json"),
                              encoding="utf-8"))
        pm, _, errs = er.run_chain(chat, "小明")
        C.ok("setup: 导入链路无错误", not errs, str(errs))
        sw.init_ex_instance(pm, base, "demo")
        pm_path = os.path.join(base, "demo", "persona_memory.json")

        host = Host(base, adapter=None, session_store_dir=sessions)
        sid = host.new_session("demo")
        host.respond(sid, "在干嘛呢")
        host.respond(sid, "不对，她其实话很多")
        props = host.pending_proposals(sid)
        C.ok("纠正: 产生提议", len(props) > 0, str(props))
        if not props:
            return
        res = host.confirm_proposal(sid, props[0]["proposal_id"])
        C.ok("纠正: 写回成功", res.get("ok") and res.get("revision") == 2, str(res))

        saved = json.load(open(pm_path, encoding="utf-8"))
        C.ok("落盘: corrections 有 active 记录",
             any(c.get("status") == "active" and c.get("corrected_value") == "话很多"
                 for c in saved.get("corrections", [])))

        # 模拟重启：完全新的 Host + 新会话
        host2 = Host(base, adapter=None, session_store_dir=sessions)
        sid2 = host2.new_session("demo")
        rt2 = host2.get_runtime("demo")

        # 直接断言 loader：输出里已有投影后的纠正（防断开接线）
        loaded = pl.load_runtime_persona(saved, None)
        flat = [it for b in loaded.get("memory", {}).values() for it in b]
        C.ok("loader: 输出包含纠正投影",
             any(it.get("content") == "话很多" and it.get("status") == "active" for it in flat))

        # 检索
        r = mr.retrieve(rt2.persona_memory, {}, "她话多吗", k=5)
        C.ok("检索: 纠正可召回",
             any(x["memory"].get("content") == "话很多" for x in r["items"]),
             str([x["memory"].get("content") for x in r["items"]]))

        # 追问 + 组装上下文（used 里存的是条目 id，不是文本）
        corrected_ids = {x["memory"].get("id") for x in r["items"]
                         if x["memory"].get("content") == "话很多"}
        out = host2.respond(sid2, "她话多吗")
        used = out.get("used", {}) or {}
        used_ids = set(used.get("retrieved_candidates", []) or []) | \
            set(used.get("memory_items", []) or [])
        C.ok("追问: 使用了纠正记忆", bool(corrected_ids & used_ids),
             f"corrected={corrected_ids} used={sorted(used_ids)}")
        ctx = ca.assemble(rt2.persona_memory, "小明", "她话多吗", retrieved=r, session_recent=[])
        C.ok("上下文: system_text 含新值", "话很多" in ctx["system_text"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    print("=== 纠正跨会话召回回归测试 ===")
    t_recall_after_restart()
    print(f"\n通过 {C.ok_n} / 失败 {C.fail_n}")
    for f in C.fails:
        print("  -", f)
    sys.exit(0 if C.fail_n == 0 else 1)


if __name__ == "__main__":
    main()
