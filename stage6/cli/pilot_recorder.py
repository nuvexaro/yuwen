#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Real User Pilot recorder（观测基础设施，Non-Frozen，不改产品逻辑）。

给真实用户的引导脚本：走完 create→import→chat→correction→persist→return 链，
并结构化记录每步行为/时间/轮数 + 结束时问卷。

产出：stage6/cli/pilot_data/<user_id>.json —— 供 Stage 6.x 汇总
（完成率/失败点/轮数/correction/回访/反馈/流失点；脱敏，无 key/正文。）

Pilot 原则：Observe→Measure→Classify→Decide；不改 Runtime；单用户反馈不立即改。
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.join(_HERE, "..", "host"), os.path.join(_HERE, "..", "..")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import mvp_cli  # noqa: E402


def _q(prompt, default=""):
    try:
        return input(prompt).strip() or default
    except (EOFError, KeyboardInterrupt):
        return default or "__abort__"


def _save(rec, user_id):
    # 用户可写数据根（正式 EXE 不写 bundle）
    from userdata import pilot_data_dir
    outdir = pilot_data_dir()
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, f"{user_id}.json")
    json.dump(rec, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return path


def run_pilot(user_id: str | None = None):
    user_id = user_id or uuid.uuid4().hex[:8]
    rec = {"user_id": user_id, "ts_start": time.time(), "steps": {}, "events": [], "feedback": {}}
    from userdata import exes_dir, sessions_dir
    base = os.path.join(exes_dir(), user_id)
    sess = os.path.join(sessions_dir(), user_id)
    os.environ["EX_BASE_DIR"] = base
    os.environ["EX_SESSION_DIR"] = sess
    # 默认真实模型；外部显式 EX_REAL=0 时保留离线（不联网、不需要 key）
    os.environ.setdefault("EX_REAL", "1")
    os.makedirs(base, exist_ok=True); os.makedirs(sess, exist_ok=True)

    print("=== Ex Pilot 引导 ===")
    # Step 1: create
    slug = _q("1) 给这个 Ex 起个代号(小写字母/数字,如 xiaoming): ", "")
    if slug == "__abort__" or not slug:
        rec["steps"]["create"] = {"ok": False, "reason": "abort_or_empty"}
        _save(rec, user_id); return rec
    try:
        from skill_writer_v12 import init_ex_instance
        seed = {"schema_version": "1.2", "revision": 1,
                "persona": {"layer0_rules": {}, "identity": {"name_or_alias": {
                    "claim_id": "pc_n", "value": slug, "evidence_ids": [], "confidence": 1.0,
                    "basis": "user_report_only"}}, "speech_style": {}, "emotional_pattern": {},
                    "relationship_behavior": {}},
                "memory": {k: [] for k in ("preferences", "timeline", "shared_experiences", "conflicts",
                                           "happy_memories", "breakup", "inside_jokes", "core_facts",
                                           "daily_patterns")}, "corrections": []}
        init_ex_instance(seed, base, slug)
        rec["steps"]["create"] = {"ok": True, "slug": slug}
        print("✓ 已创建")
    except Exception as e:
        rec["steps"]["create"] = {"ok": False, "reason": str(e)}
        _save(rec, user_id); return rec

    # Step 2: import (offer sample or their file)
    print("\n2) 导入聊天记录。")
    print("   选项A: 用内置示例 messages（演示用）")
    print("   选项B: 提供你自己的 ChatImport JSON 路径")
    imp = _q("   选 A/B [A]: ", "A")
    if imp.upper() == "A":
        import shutil
        # 内置示例：packaged resource（EXE 根/_MEIPASS/cwd）优先，开发模式回退仓库示例。
        from userdata import resolve_sample_path
        src = resolve_sample_path()
        pm_import_path = src
        rec["steps"]["import"] = {"ok": True, "source": "sample_case_001",
                                  "src": os.path.basename(src) if src and os.path.exists(src) else "missing"}
        if not src or not os.path.exists(src):
            rec["steps"]["import"]["ok"] = False
            rec["steps"]["import"]["err"] = f"示例文件不存在: {src}"
            print("   （示例文件缺失）")
        else:
            print("   （示例导入走 eval_runner 5.2-5.5；此处为引导演示，真实用户应提供自己文件）")
        # 用示例跑真实 import 链以完成端到端（用户若选 A 我们演示建 persona）
        try:
            import eval_runner as er
            chat = json.load(open(src, encoding="utf-8"))
            pm, _, errs = er.run_chain(chat, name=slug)
            if pm:
                json.dump(pm, open(os.path.join(base, slug, "persona_memory.json"), "w", encoding="utf-8"),
                          ensure_ascii=False, indent=2)
                rec["steps"]["import"]["persona_built"] = True
                print("✓ 已生成 persona")
            else:
                rec["steps"]["import"]["ok"] = False; rec["steps"]["import"]["err"] = errs
                print("导入失败:", errs)
        except Exception as e:
            rec["steps"]["import"]["ok"] = False; rec["steps"]["import"]["err"] = str(e)
            print("导入异常:", e)
    else:
        p = _q("   你的 ChatImport JSON 路径: ", "")
        rec["steps"]["import"] = {"ok": bool(p), "source": "user_file" if p else "none"}
        if p:
            try:
                import eval_runner as er
                chat = json.load(open(p, encoding="utf-8"))
                pm, _, errs = er.run_chain(chat, name=slug)
                if pm:
                    json.dump(pm, open(os.path.join(base, slug, "persona_memory.json"), "w", encoding="utf-8"),
                              ensure_ascii=False, indent=2)
                    rec["steps"]["import"]["persona_built"] = True
                    print("✓ persona 已生成")
                else:
                    rec["steps"]["import"]["err"] = errs; print("导入失败:", errs)
            except Exception as e:
                rec["steps"]["import"]["err"] = str(e); print("导入异常:", e)
        else:
            print("（跳过导入；用空 persona 继续聊天）")

    # Step 3: chat (multi-turn, count turns, detect correction + confirm)
    host = mvp_cli.make_host()
    try:
        sid = host.new_session(slug)
    except Exception as e:
        rec["steps"]["chat"] = {"ok": False, "reason": str(e)}
        _save(rec, user_id); return rec
    rec["steps"]["chat"] = {"ok": True, "turns": 0, "corrections": 0, "confirms": 0, "rejects": 0}
    print("\n3) 开始聊天。多聊几轮。想纠正 ta 就正常说（如：不对，她其实话痨）。")
    print("   /quit 结束聊天，然后回答问卷。")
    while True:
        u = _q("你> ", "")
        if u in ("__abort__", "/quit", "/quit", "/q"):
            break
        if not u:
            continue
        rec["steps"]["chat"]["turns"] += 1
        try:
            out = host.respond(sid, u)
        except Exception as e:
            rec["events"].append({"t": "chat_error", "msg": str(e)})
            print("（出错:", e, "）")
            continue
        print(f"ta> {out.get('assistant_response','')}")
        if out.get("error") == "gateway_fallback":
            # 最小安全错误观测（Non-Frozen）：读 real_llm_adapter 模块级的安全失败记录，
            # 附上 exception type / http_status / scrubbed message。绝不记录 key/header/secret。
            detail = {}
            try:
                import real_llm_adapter as _rla
                detail = _rla.last_error_safe()
            except Exception:
                detail = {}
            ev = {"t": "gateway_fallback"}
            if detail and detail.get("type"):
                ev["detail"] = {"type": detail.get("type"),
                                "http_status": detail.get("http_status"),
                                "message": detail.get("message")}
            rec["events"].append(ev)
            print("（服务没响应）")
        # correction proposal offer
        try:
            props = host.pending_proposals(sid)
        except Exception:
            props = []
        for p in props:
            rec["steps"]["chat"]["corrections"] += 1
            print(f"\n  纠正建议: 把 {p.get('target_id')} 纠正为「{p.get('corrected_value')}」")
            ans = _q("  确认?(y/n) [n]: ", "n")
            if ans.lower() == "y":
                try:
                    host.confirm_proposal(sid, p["proposal_id"])
                    rec["steps"]["chat"]["confirms"] += 1
                    print("  ✓ 已记住")
                except Exception as e:
                    rec["events"].append({"t": "persist_error", "msg": str(e)})
            else:
                rec["steps"]["chat"]["rejects"] += 1
                print("  已忽略")
    # quit chat
    rec["steps"]["chat"]["ended"] = True

    # questionnaire
    print("\n=== 简短问卷 ===")
    rec["feedback"]["like_ta"] = _q("1) 像不像 ta？(1不像-5很像) [3]: ", "3")
    rec["feedback"]["most_like"] = _q("2) 最像的地方: ", "")
    rec["feedback"]["least_like"] = _q("3) 最不像/出戏的地方: ", "")
    rec["feedback"]["will_return"] = _q("4) 明天还愿意回来聊吗？(y/n) [y]: ", "y")
    rec["feedback"]["memory_ok"] = _q("5) 它记得你纠正过的吗？(y/n/没试) [没试]: ", "没试")
    rec["feedback"]["correction_ux"] = _q("6) 纠正流程打断感？(1很打断-5很顺) [3]: ", "3")
    rec["feedback"]["friction"] = _q("7) 在哪一步卡住/想退出: ", "")
    rec["feedback"]["open"] = _q("8) 其他想说的: ", "")
    rec["ts_end"] = time.time()
    path = _save(rec, user_id)
    print("\n已保存记录:", path)
    return rec


if __name__ == "__main__":
    uid = sys.argv[1] if len(sys.argv) > 1 else None
    run_pilot(uid)
