#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MVP chat session loop（CLI Product Layer）。Non-Frozen。

交互：
  输入消息 → Host.respond → 显示回复
  若 runtime 产 correction proposal → 询问 confirm/reject
  confirm → Host.confirm_proposal → persist
  退出后再次进入 → 新 session（Host 从 canonical reload 长期记忆）
核心语义全在 Host / Frozen Runtime；本文件只做 I/O 与文案。
"""

from __future__ import annotations

import os
import sys

from mvp_cli import make_host


def _classify_error(error: str | None) -> str | None:
    """把 runtime error signal 翻译成用户可懂文案（不混入 Frozen 错误语义）。"""
    if error == "gateway_fallback":
        return "（网络/服务暂时没响应，ta 没接上话。请稍后再试。）"
    if error == "context_budget_exceeded":
        return "（这条太长，接不住，换个说法？）"
    return None


def run_chat_session(ex: str):
    host = make_host()
    try:
        sid = host.new_session(ex)
    except Exception as e:
        print(f"进入会话失败: {e}")
        return 1
    print(f"进入 Ex [{ex}] 会话 {sid}（输入 /quit 退出，/correction 查看待确认纠正）")
    while True:
        try:
            u = input("你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已退出。")
            return 0
        if u in ("/quit", "/exit", "/q"):
            print("已退出。下次进入会自动加载长期记忆。")
            return 0
        if u in ("/correction", "/corr"):
            _show_proposals(host, sid, ex)
            continue
        if u in ("/memory", "/mem"):
            _show_memory(host, sid, ex)
            continue
        if not u:
            continue
        try:
            out = host.respond(sid, u)
        except Exception as e:
            print(f"（出错了: {e}）")
            continue
        err_msg = _classify_error(out.get("error"))
        print(f"ta> {out.get('assistant_response', '')}")
        if err_msg:
            print(err_msg)
        _offer_proposals(host, sid, ex)
        _offer_memory_proposals(host, sid, ex)


def _proposals(host, sid):
    try:
        return host.pending_proposals(sid)
    except Exception:
        return []


def _show_proposals(host, sid, ex):
    props = _proposals(host, sid)
    if not props:
        print("（当前没有待确认的纠正）")
        return
    for p in props:
        print(f"  [纠正] {p.get('corrected_value')}  →  覆盖旧值（{p.get('target_id')}）"
              f"  proposal_id={p.get('proposal_id')}")


def _offer_proposals(host, sid, ex):
    props = _proposals(host, sid)
    for p in props:
        print(f"\n检测到纠正建议：把「{p.get('target_id')}」纠正为「{p.get('corrected_value')}」")
        ans = input("确认这条纠正？(y=确认 / n=忽略 / s=跳过本次) > ").strip().lower()
        if ans == "y":
            try:
                res = host.confirm_proposal(sid, p["proposal_id"])
                print(f"已持久化（revision {res.get('revision')}）。长期记忆已更新。")
            except Exception as e:
                print(f"持久化失败: {e}")
        else:
            print("已忽略，本次不写入长期记忆。")


# ---------------- G3 Memory Item Lifecycle（New-fact proposal）----------------

def _memory_props(host, sid):
    """G3-3：只返回 bucket 明确的 proposal；fallback 项 Host 侧已不返回。"""
    try:
        return host.pending_memory_proposals(sid)
    except Exception:
        return []


def _show_memory(host, sid, ex):
    props = _memory_props(host, sid)
    if not props:
        print("（当前没有待确认的新信息）")
        return
    for p in props:
        print(f"  [新信息] {p.get('text')}  →  分类：{p.get('bucket')}"
              f"  proposal_id={p.get('proposal_id')}")


def _offer_memory_proposals(host, sid, ex):
    for p in _memory_props(host, sid):
        print(f"\n检测到新信息：「{p.get('text')}」")
        ans = input("记入长期记忆？(y=记住 / n=不记) > ").strip().lower()
        if ans == "y":
            try:
                res = host.decide_memory_proposal(sid, p["proposal_id"], True)
                print(f"已记住（revision {res.get('revision')}）。")
            except Exception as e:
                print(f"写入失败: {e}")
        else:
            print("已跳过，本次不写入长期记忆。")
