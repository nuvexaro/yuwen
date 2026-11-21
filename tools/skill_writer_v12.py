#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Distribution Wrapper / F2 — skill_writer v1.2：Ex Instance Initializer（Non-Frozen）。

从 seed persona_memory v1.2 初始化一个独立 Ex Instance：

    exes/{slug}/
    ├── SKILL.md            # trigger/distribution shell（frontmatter + 指向说明，零人格事实）
    ├── persona_memory.json # = 该 Ex Instance 唯一 canonical long-term state（初始=seed）
    ├── chat.py             # 薄 Runtime entry 模板（load → persona_loader → PersonaRuntime；confirmed → instance_persistence）
    ├── meta.json           # slug/name/version/profile
    └── versions/           # version_manager 备份目标

纪律：
  - persona_memory.json 从 seed 初始化；seed ≠ Instance current state（Instance 此后独立演化）。
  - 不创建第二份 canonical；不改 persona_memory schema。
  - SKILL.md 禁止写人格/memory 事实（仅 frontmatter + 运行说明）。
  - chat.py 是模板，不重写 PersonaRuntime / correction semantics / 不做 fake host。
  - 本文件为新增（tools/skill_writer_v12.py），不修改旧 tools/skill_writer.py → legacy 不破坏。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime


def _valid_slug(slug: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9\-_]{0,40}", slug or ""))


def _validate_seed(pm: dict) -> None:
    if not isinstance(pm, dict):
        raise ValueError("seed persona_memory 非 dict")
    for k in ("schema_version", "revision", "persona", "memory", "corrections"):
        if k not in pm:
            raise ValueError(f"seed persona_memory 缺 {k}")
    if not isinstance(pm.get("memory"), dict):
        raise ValueError("seed memory 非 dict")


def _default_meta(slug: str, name: str, profile: dict) -> dict:
    return {
        "slug": slug,
        "name": name or slug,
        "version": "v1",
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "profile": profile or {},
        "instance": {"format": "v1.2", "canonical": "persona_memory.json"},
    }


SKILL_MD_TEMPLATE = """---
name: ex-{slug}
description: An ex-partner conversation instance. Load persona_memory.json via persona_loader/PersonaRuntime. 前任对话实例（人格/记忆见 persona_memory.json）。
user-invocable: true
allowed-tools: Read, Write, Bash
---

# Ex Instance `{slug}`

本 skill 是一个"前任"对话实例。人格与记忆的唯一事实源是 `persona_memory.json`
（persona_memory v1.2）。运行方式：执行 `chat.py`（加载 `persona_memory.json` →
persona_loader → PersonaRuntime → respond）。

本文件只是触发/分发壳，**不包含任何前任的人格或记忆事实**（名字、性格、共同记忆等
一律在 `persona_memory.json` 中，由运行时加载，不复制到本文件）。

> Canonical Source Contract：persona_memory.json 是唯一长期事实源；
> session 状态与 correction 持久由 runtime + instance_persistence 负责。
"""

CHAT_PY_TEMPLATE = '''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ex Instance Runtime entry（薄模板，由 skill_writer v1.2 生成，可被外部 host 调用）。

本文件只做 Runtime entry/wrapper：
  load persona_memory.json
    → persona_loader.load_runtime_persona(...)
    → PersonaRuntime(real gateway)
    → respond(...)
confirmed correction
    → instance_persistence.write_back(persona_memory.json, ...)

不重新实现 PersonaRuntime / correction semantics；真实多轮对话编排与 API key 配置属
External Production Host，不在本文件内伪造。
"""

import json
import os
import sys

# 允许从仓库 runtime 目录或已安装位置导入（按实际部署调整路径）
_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.join(_HERE, "runtime"),
           os.path.abspath(os.path.join(_HERE, "..", ".."))):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def load_instance(persona_memory_path: str, session_overlay=None):
    """返回 (transient_pm, runtime_cls_kwargs)。"""
    from persona_loader import load_runtime_persona
    with open(persona_memory_path, encoding="utf-8") as f:
        longterm = json.load(f)
    base = load_runtime_persona(longterm, session_overlay or [])
    return base, longterm


def make_runtime(base_pm, adapter=None, model="mock"):
    """构造 PersonaRuntime。真实对话由外部 host 提供 adapter（如 real_llm_adapter）。"""
    from persona_runtime import PersonaRuntime
    from llm_gateway import LLMGateway
    gw = LLMGateway(adapter=adapter, model=model)
    return PersonaRuntime(persona_memory=base_pm, gateway=gw)


def respond_once(runtime, user_message, session_id=None):
    """单轮 respond。confirmed correction 由调用方（host）经 instance_persistence 落盘。"""
    return runtime.respond(user_message, session_id=session_id)


def persist_confirmed(persona_memory_path: str, confirmed_statements, backup_dir=None):
    """把 confirmed corrections 写回 Instance canonical（用该 Instance 的稳定共享锁）。

    同一 Ex 的多 session 写回共享同一把锁（get_instance_lock），不做各自独立锁。
    """
    from instance_persistence import write_back, get_instance_lock
    lock = get_instance_lock(persona_memory_path)
    return write_back(persona_memory_path, confirmed_statements,
                      backup_dir=backup_dir, lock=lock)


if __name__ == "__main__":
    # 最薄 CLI：读取 persona_memory.json 并跑一轮（供最小验证；完整对话编排属外部 host）
    pm_path = os.path.join(_HERE, "persona_memory.json")
    if not os.path.exists(pm_path):
        sys.exit("缺少 persona_memory.json")
    base, _ = load_instance(pm_path)
    rt = make_runtime(base)
    msg = sys.argv[1] if len(sys.argv) > 1 else "在吗"
    out = respond_once(rt, msg)
    print(out.get("assistant_response", ""))
'''


def init_ex_instance(seed_pm: dict, base_dir: str, slug: str, *,
                     name: str = "", profile: dict = None,
                     description: str = "") -> str:
    """从 seed v1.2 初始化 Ex Instance，返回 exes/{slug} 目录路径。"""
    if not _valid_slug(slug):
        raise ValueError(f"非法 slug: {slug!r}")
    _validate_seed(seed_pm)
    skill_dir = os.path.join(base_dir, slug)
    if os.path.exists(skill_dir):
        raise FileExistsError(f"Ex Instance 已存在: {skill_dir}")
    # 目录
    for d in ("", "versions", "memories", "memories/chats", "memories/photos", "memories/social"):
        os.makedirs(os.path.join(skill_dir, d), exist_ok=True)
    # 1) persona_memory.json = Instance canonical（初始 = seed）
    pm_path = os.path.join(skill_dir, "persona_memory.json")
    with open(pm_path, "w", encoding="utf-8") as f:
        json.dump(seed_pm, f, ensure_ascii=False, indent=2)
    # 2) SKILL.md = 纯触发壳（零人格事实：不注入 name/description/profile，只注入中性 slug）
    with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(SKILL_MD_TEMPLATE.format(slug=slug))
    # 3) chat.py = 薄 Runtime entry 模板
    with open(os.path.join(skill_dir, "chat.py"), "w", encoding="utf-8") as f:
        f.write(CHAT_PY_TEMPLATE)
    # 4) meta.json
    meta = _default_meta(slug, name, profile or {})
    with open(os.path.join(skill_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return skill_dir


def main(argv=None):
    ap = argparse.ArgumentParser(description="skill_writer v1.2 — Ex Instance Initializer")
    ap.add_argument("--seed", required=True, help="seed persona_memory v1.2 JSON 路径")
    ap.add_argument("--slug", required=True)
    ap.add_argument("--name", default="")
    ap.add_argument("--base-dir", default="./exes")
    ap.add_argument("--profile", default=None, help="可选 profile JSON 路径")
    ap.add_argument("--description", default="")
    args = ap.parse_args(argv)
    with open(args.seed, encoding="utf-8") as f:
        seed = json.load(f)
    profile = None
    if args.profile:
        with open(args.profile, encoding="utf-8") as f:
            profile = json.load(f)
    d = init_ex_instance(seed, args.base_dir, args.slug, name=args.name,
                         profile=profile, description=args.description)
    print(f"已初始化 Ex Instance: {d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
