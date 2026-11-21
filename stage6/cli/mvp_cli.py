#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 6.3 — MVP CLI（Product Surface）。Non-Frozen。

CLI Product Layer → Production Host (stage6.host) → Frozen Runtime。

职责：命令路由 + 用户交互 + 文案 + 引导。核心语义全部委托 Host/现有管道。
禁止：复制 persona/memory 逻辑；把 CLI 逻辑塞进 Host。
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.join(_HERE, "..", "host"), os.path.join(_HERE, "..", ".."),
           os.path.join(_HERE, "..", "..", "tools"),
           os.path.join(_HERE, "..", "..", "evaluation"),
           os.path.join(_HERE, "..", "..", "benchmark")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from production_host import Host, HostError  # noqa: E402


def _base_dir() -> str:
    # 默认落到用户可写数据根（.ex_ai/exes）；env 可覆盖（测试/开发）
    from userdata import exes_dir
    return os.environ.get("EX_BASE_DIR") or exes_dir()


def _store_dir() -> str:
    from userdata import sessions_dir
    return os.environ.get("EX_SESSION_DIR") or sessions_dir()


def _default_model() -> str:
    return os.environ.get("EX_MODEL", "deepseek-chat")


def _provider() -> str:
    return os.environ.get("EX_PROVIDER", "openai")


def _make_adapter():
    """real adapter from env (DEEPSEEK_API / OPENAI_API_KEY + OPENAI_BASE_URL)。key 不落盘/不入日志。"""
    # CLI 不打印/不存储 key；仅构建时从 env 读取
    if _provider() == "openai":
        import real_llm_adapter as rla
        return rla.make_provider_adapter("openai")
    return None


def make_host(model: str | None = None, adapter=None) -> Host:
    model = model or _default_model()
    if adapter is None and os.environ.get("EX_REAL", "1") == "1":
        try:
            adapter = _make_adapter()
        except Exception:
            adapter = None  # fallback -> mock for non-real usage (unit), Real E2E must set env
    return Host(_base_dir(), adapter=adapter, model=model, session_store_dir=_store_dir())


# ---------------- create / import ----------------
def cmd_create(args):
    """创建空 Ex（slug）或用 --seed 直接建。"""
    from skill_writer_v12 import init_ex_instance, _valid_slug
    slug = args.slug
    if not _valid_slug(slug):
        print(f"非法 slug: {slug!r}（仅小写字母/数字/-/_，≤40）")
        return 1
    if args.seed:
        with open(args.seed, encoding="utf-8") as f:
            seed = json.load(f)
    else:
        # 空 seed：最小 persona_memory（无 memory；用户后续 import 补）
        seed = {"schema_version": "1.2", "revision": 1,
                "persona": {"layer0_rules": {}, "identity": {"name_or_alias": {
                    "claim_id": "pc_n", "value": args.name or slug, "evidence_ids": [],
                    "confidence": 1.0, "basis": "user_report_only"}},
                    "speech_style": {}, "emotional_pattern": {}, "relationship_behavior": {}},
                "memory": {k: [] for k in ("preferences", "timeline", "shared_experiences", "conflicts",
                                           "happy_memories", "breakup", "inside_jokes", "core_facts",
                                           "daily_patterns")}, "corrections": []}
    try:
        d = init_ex_instance(seed, _base_dir(), slug, name=args.name or slug)
    except FileExistsError:
        print(f"Ex 已存在: {slug}")
        return 1
    print(f"已创建 Ex: {d}")
    print("下一步: 导入聊天记录 → ex-cli import --ex <slug> --chat <messages.json>")
    return 0


def cmd_import(args):
    """导入 ChatImport JSON → persona_memory → 写入该 Ex 的 canonical。"""
    import eval_runner as er
    slug = args.ex
    with open(args.chat, encoding="utf-8") as f:
        chat = json.load(f)
    pm, _, errors = er.run_chain(chat, name=args.name or slug)
    if pm is None:
        print("导入失败:", errors)
        return 1
    # 写回 Ex canonical（persona_memory.json）
    pm_path = os.path.join(_base_dir(), slug, "persona_memory.json")
    if not os.path.exists(os.path.dirname(pm_path)):
        print(f"Ex 不存在: {slug}（先 create）")
        return 1
    with open(pm_path, "w", encoding="utf-8") as f:
        json.dump(pm, f, ensure_ascii=False, indent=2)
    print(f"已导入并更新 canonical: {pm_path}（schema {pm.get('schema_version')}, revision {pm.get('revision')}）")
    return 0


def cmd_list(args):
    """列出所有 Ex。"""
    base = _base_dir()
    if not os.path.isdir(base):
        print("还没有任何 Ex。用 `ex-cli create --slug <x>` 创建。")
        return 0
    for slug in sorted(os.listdir(base)):
        pm = os.path.join(base, slug, "persona_memory.json")
        if os.path.exists(pm):
            try:
                with open(pm, encoding="utf-8") as f:
                    meta = json.load(f)
                name = (meta.get("persona", {}).get("identity", {}).get("name_or_alias") or {}).get("value", slug)
            except Exception:
                name = slug
            print(f"  {slug}  ({name})")
    return 0


def cmd_delete(args):
    """删除 Ex 及其全部本地数据（canonical + sessions + versions）。"""
    import shutil
    slug = args.ex
    removed = []
    for d in (os.path.join(_base_dir(), slug), os.path.join(_store_dir(), slug)):
        if os.path.isdir(d):
            shutil.rmtree(d)
            removed.append(d)
    if not removed:
        print(f"Ex 不存在: {slug}")
        return 1
    print("已删除:", "; ".join(removed))
    return 0


def cmd_chat(args):
    """进入对话：real multi-turn + correction proposal/confirm/reject + persist。"""
    from mvp_session import run_chat_session
    return run_chat_session(args.ex)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ex-cli", description="Ex MVP CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_create = sub.add_parser("create"); p_create.add_argument("--slug", required=True)
    p_create.add_argument("--name", default=""); p_create.add_argument("--seed", default=None)
    p_import = sub.add_parser("import"); p_import.add_argument("--ex", required=True)
    p_import.add_argument("--chat", required=True); p_import.add_argument("--name", default="")
    p_list = sub.add_parser("list")
    p_del = sub.add_parser("delete"); p_del.add_argument("--ex", required=True)
    p_chat = sub.add_parser("chat"); p_chat.add_argument("--ex", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "create":
        return cmd_create(args)
    if args.cmd == "import":
        return cmd_import(args)
    if args.cmd == "list":
        return cmd_list(args)
    if args.cmd == "delete":
        return cmd_delete(args)
    if args.cmd == "chat":
        return cmd_chat(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
