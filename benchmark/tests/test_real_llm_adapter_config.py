#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""real_llm_adapter 配置回归测试（Non-Frozen，根治 base_url 依赖）。

覆盖（2026-09-08 修复后）：
  1. 显式 OPENAI_BASE_URL=https://api.deepseek.com → openai client 使用 DeepSeek base_url。
  2. OPENAI_BASE_URL 未设置 → client 仍默认 https://api.deepseek.com（DEEPSEEK_DEFAULT_BASE_URL）。
  3. 绝不默认回退到 https://api.openai.com/v1。
  4. API key 永不进入日志 / 异常记录 / 安全错误观测（脱敏验证）。
  5. adapter 失败仍抛 RealLLMError（gateway fallback 上游行为不破坏）+ 记录安全 detail。

不联网：用 Fake client 捕获构造参数，不触发真实 HTTP。
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BENCH = os.path.dirname(HERE)
for _p in (BENCH,):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import real_llm_adapter as rla  # noqa: E402


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


# ---- Fake openai client：捕获构造参数，绝不联网 ----
captures = []


class _FakeCompletions:
    def create(self, **kw):
        raise TimeoutError("simulated transport failure")


class _FakeChat:
    completions = _FakeCompletions()


class _FakeClient:
    chat = _FakeChat()

    def __init__(self, *, api_key=None, base_url=None, **kw):
        captures.append({"api_key": api_key, "base_url": base_url})


# 供 real_llm_adapter 内 `import openai` 后 `openai.OpenAI(...)` 命中 fake
import openai as _real_openai  # noqa: E402


def _install_fake():
    captures.clear()
    _real_openai.OpenAI = _FakeClient


FAKE_KEY = "sk-test-abcdef1234567890-XXXX"  # 假 key，仅测试脱敏，非真实


def main():
    print("=== real_llm_adapter config regression ===")
    _install_fake()
    os.environ["OPENAI_API_KEY"] = FAKE_KEY

    # 1. 显式 base_url → 用 DeepSeek
    os.environ["OPENAI_BASE_URL"] = "https://api.deepseek.com"
    try:
        rla.openai_adapter("hi", model="m", max_tokens=8)
        C.ok("1: raised on fake transport", False, "expected RealLLMError")
    except rla.RealLLMError:
        C.ok("1: raised on fake transport", True)
    C.ok("1: explicit base_url honored",
         captures and captures[0]["base_url"] == "https://api.deepseek.com",
         str(captures[0]["base_url"]) if captures else "no capture")

    # 2. 未设置 OPENAI_BASE_URL → 默认 DeepSeek
    os.environ.pop("OPENAI_BASE_URL", None)
    try:
        rla.openai_adapter("hi", model="m", max_tokens=8)
    except rla.RealLLMError:
        pass
    C.ok("2: default base_url == DeepSeek when env unset",
         captures and captures[-1]["base_url"] == rla.DEEPSEEK_DEFAULT_BASE_URL,
         str(captures[-1]["base_url"]) if captures else "no capture")
    C.ok("2: default base_url == https://api.deepseek.com",
         captures and captures[-1]["base_url"] == "https://api.deepseek.com",
         str(captures[-1]["base_url"]) if captures else "no capture")

    # 3. 任何一次构造都不落到 api.openai.com
    bad = [c["base_url"] for c in captures if "api.openai.com" in (c["base_url"] or "")]
    C.ok("3: never falls back to api.openai.com", not bad, f"bad={bad}")
    # 显式配置为 openai.com（用户故意）→ 尊重；但默认/未设绝不落 openai.com 已在 2 覆盖
    os.environ["OPENAI_BASE_URL"] = "https://api.openai.com/v1"  # 用户显式选择
    try:
        rla.openai_adapter("hi", model="m", max_tokens=8)
    except rla.RealLLMError:
        pass
    C.ok("3: explicit api.openai.com config still honored (user choice)",
         captures and captures[-1]["base_url"] == "https://api.openai.com/v1",
         str(captures[-1]["base_url"]) if captures else "no capture")
    os.environ.pop("OPENAI_BASE_URL", None)

    # 4. key 永不进入日志/异常/安全记录
    # 4a. scrub
    s = rla._scrub(f"err prefix {FAKE_KEY} suffix Authorization: Bearer {FAKE_KEY}")
    C.ok("4a: scrub removes key+bearer", FAKE_KEY not in s and "Bearer" not in s and "[REDACTED]" in s, s)
    # 4b. RealLLMError message + last_error_safe 不含 key
    _install_fake()
    try:
        rla.openai_adapter("hi", model="m", max_tokens=8)
        C.ok("4b: raised", False)
    except rla.RealLLMError as e:
        msg = str(e)
        C.ok("4b: RealLLMError has no key", FAKE_KEY not in msg, msg[:120])
    safe = rla.last_error_safe()
    safe_str = f"{safe}"
    C.ok("4b: last_error_safe has no key", FAKE_KEY not in safe_str, safe_str[:120])
    C.ok("4b: safe detail exposes type+http_status",
         safe.get("type") == "TimeoutError" and safe.get("http_status") is None,
         safe_str[:120])

    # 5. adapter 失败仍抛 RealLLMError（gateway fallback 上游不破坏）
    #    （gateway → fallback 本身由 test_gateway_fallback_signal 覆盖；此处验证 adapter 层契约不变）
    _install_fake()
    os.environ["OPENAI_API_KEY"] = FAKE_KEY
    try:
        rla.openai_adapter("hi", model="m", max_tokens=8)
        C.ok("5: RealLLMError on transport failure", False, "did not raise")
    except rla.RealLLMError as e:
        C.ok("5: RealLLMError on transport failure", "调用失败" in str(e), str(e)[:120])

    print(f"\n通过 {C.ok_n} / 失败 {C.fail_n}")
    for f in C.fails:
        print("  -", f)
    sys.exit(0 if C.fail_n == 0 else 1)


if __name__ == "__main__":
    main()
