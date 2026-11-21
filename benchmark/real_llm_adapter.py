#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Real LLM Adapter（provider-neutral，适配现有 LLMGateway(adapter=...)）。

支持：mock / anthropic / openai。API key 仅从环境变量读取；不入代码/日志/result。
无 key 或 SDK 缺失 → 抛 RealLLMUnavailable（不伪造调用）。
adapter 接收的是 gateway 拼接的 prompt（system+user 已在其中）；provider 内部转 messages。

provider-specific 逻辑只在 adapter；PersonaRuntime 不含。
"""

from __future__ import annotations

import os
import re
import time
from typing import Optional


# 显式配置缺省时的安全默认：DeepSeek OpenAI-compatible endpoint。
# 绝不默认落到 OpenAI 官方 endpoint（https://api.openai.com/v1）——那会用 DeepSeek key 打错 host。
DEEPSEEK_DEFAULT_BASE_URL = "https://api.deepseek.com"


class RealLLMUnavailable(Exception):
    pass


class RealLLMError(Exception):
    pass


def _require_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise RealLLMUnavailable(f"缺少环境变量 {name}（真实 LLM benchmark 需 API key）")
    return v


# ---------------------------------------------------------------------------
# 最小安全错误观测（Non-Frozen）。
# 目的：真实 LLM 调用失败时，让 Host / Pilot 能知道 exception type + HTTP status +
#       安全的 error message，而不吞掉底层原因。
# 铁律：绝不记录 API key / Authorization header / 完整请求头 / 任何 secret。
# ---------------------------------------------------------------------------
# --- DIAGNOSTIC (2026-09-08, Stage 6.3 Clean-Windows 无回复定位) -------------
# attempt 级安全日志：每次真实调用(成功或失败)追加一行 safe metadata 到
# <EX_DATA_ROOT 或系统临时目录>/exai_llm_diag.log。仅 base_url/model/http_status/
# exception type / scrubbed message / 成功标记。绝不写 key / auth header / 请求头。
# 定位后应移除（临时诊断代码，非正式修复）。
# ---------------------------------------------------------------------------

_SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9_\-]{6,}"
    r"|Bearer\s+[A-Za-z0-9_\-.\/]{6,}"
    r"|authorization['\"]?\s*[:=]\s*['\"][^'\"]{6,}"
    r"|api[_\-]?key['\"]?\s*[:=]\s*['\"][^'\"]{6,})",
    re.IGNORECASE,
)

# 模块级最近一次真实 LLM 失败的安全记录（仅内存，进程结束即失；不含任何 secret）。
_last_error: dict = {"type": None, "http_status": None, "message": None, "at": None}


def _scrub(text: str) -> str:
    """脱敏：把形似 key / Bearer / authorization / api-key 的内容替换为 [REDACTED]。"""
    if not text:
        return ""
    return _SECRET_RE.sub("[REDACTED]", str(text))


def _record_error(exc: Exception) -> None:
    """从 SDK 异常提取 type + HTTP status + scrubbed message，写入模块级记录。"""
    status = getattr(exc, "status_code", None)
    if status is None:
        resp = getattr(exc, "response", None)
        if resp is not None:
            status = getattr(resp, "status_code", None)
    _last_error.update({
        "type": type(exc).__name__,
        "http_status": status,
        "message": _scrub(str(exc))[:500],
        "at": time.time(),
    })


def last_error_safe() -> dict:
    """最近一次真实 LLM 失败的安全记录副本（无 key / header / secret）。Non-Frozen 层观测用。"""
    return dict(_last_error)


# --- DIAGNOSTIC: attempt-level safe log (temp; see marker above) ------------


def _diag_log(provider: str, *, base_url: str, model: str, ok: bool,
              exc_type: str = "", http_status=None, exc_msg: str = "") -> None:
    """把一次真实调用的 safe metadata 追加到诊断日志。绝不写 key/auth/headers。"""
    try:
        import tempfile
        log_dir = os.environ.get("EX_DATA_ROOT") or tempfile.gettempdir()
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "exai_llm_diag.log")
        line = {
            "at": time.time(), "provider": provider, "base_url": base_url,
            "model": model, "ok": bool(ok),
            "exc_type": exc_type, "http_status": http_status,
            "exc_msg": _scrub(exc_msg)[:300],
        }
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(("DIAG " if ok else "DIAG-FAIL ") + str(line) + "\n")
    except Exception:
        pass  # 诊断日志绝不影响主流程
# --- /DIAGNOSTIC ------------------------------------------------------------


def anthropic_adapter(prompt: str, *, model: Optional[str] = None, max_tokens: int = 512,
                      temperature: float = 0.7):
    """Anthropic Claude adapter。key=ANTHROPIC_API_KEY。"""
    _require_env("ANTHROPIC_API_KEY")
    try:
        import anthropic  # noqa: WPS433
    except ImportError as e:
        raise RealLLMUnavailable("anthropic SDK 未安装") from e
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    mdl = model or "claude-sonnet-5-20251001"
    t0 = time.time()
    try:
        resp = client.messages.create(
            model=mdl, max_tokens=max_tokens, temperature=temperature,
            system=prompt,  # gateway prompt 已含 system+user 文本；此处整体作为 system
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        _record_error(e)
        _diag_log("anthropic", base_url=os.environ.get("ANTHROPIC_BASE_URL", ""), model=mdl, ok=False,
                  exc_type=type(e).__name__, http_status=getattr(e, "status_code", None),
                  exc_msg=str(e))
        raise RealLLMError(f"anthropic 调用失败: {type(e).__name__}: {_scrub(str(e))}") from e
    usage = getattr(resp, "usage", None)
    tokens = None
    if usage is not None:
        tokens = {"input": getattr(usage, "input_tokens", None),
                  "output": getattr(usage, "output_tokens", None)}
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    _diag_log("anthropic", base_url=os.environ.get("ANTHROPIC_BASE_URL", ""), model=mdl, ok=True,
              exc_msg=f"text_len={len(text or '')}")
    return {"text": text, "usage": tokens, "model": mdl, "model_version": None,
            "latency_ms": (time.time() - t0) * 1000}


def openai_adapter(prompt: str, *, model: Optional[str] = None, max_tokens: int = 512,
                   temperature: float = 0.7):
    """OpenAI adapter。key=OPENAI_API_KEY。"""
    _require_env("OPENAI_API_KEY")
    try:
        import openai  # noqa: WPS433
    except ImportError as e:
        raise RealLLMUnavailable("openai SDK 未安装") from e
    _base = os.environ.get("OPENAI_BASE_URL") or DEEPSEEK_DEFAULT_BASE_URL
    client = openai.OpenAI(
        api_key=os.environ["OPENAI_API_KEY"],
        # 显式传 base_url：尊重 OPENAI_BASE_URL 配置；缺省安全默认 DeepSeek。
        # 不依赖 client 构造时 env 是否已被正确读取；绝不默认落 OpenAI 官方 endpoint。
        base_url=_base,
    )
    mdl = model or "gpt-4o-mini"
    t0 = time.time()
    try:
        resp = client.chat.completions.create(
            model=mdl, max_tokens=max_tokens, temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        _record_error(e)
        _diag_log("openai", base_url=_base, model=mdl, ok=False,
                  exc_type=type(e).__name__, http_status=getattr(e, "status_code", None),
                  exc_msg=str(e))
        raise RealLLMError(f"openai 调用失败: {type(e).__name__}: {_scrub(str(e))}") from e
    usage = getattr(resp, "usage", None)
    tokens = None
    if usage is not None:
        tokens = {"input": usage.prompt_tokens, "output": usage.completion_tokens}
    text = resp.choices[0].message.content or ""
    _diag_log("openai", base_url=_base, model=mdl, ok=True,
              exc_msg=f"text_len={len(text or '')}")
    return {"text": text, "usage": tokens, "model": mdl, "model_version": None,
            "latency_ms": (time.time() - t0) * 1000}


def make_provider_adapter(provider: str):
    """返回适配 LLMGateway(adapter=...) 的 callable：(prompt, *, model,max_tokens,temperature) -> str。

    真实调用会更新一个共享 usage/latency 寄存器；无 key → 抛 RealLLMUnavailable。
    mock → 需要 responder（由 harness 注入），此函数不处理 mock。
    """
    # eager key 校验：构造 adapter 即检查 key/SDK，避免"无 key 却静默 fallback 成 PASS"
    if provider == "anthropic":
        _require_env("ANTHROPIC_API_KEY")
        try:
            import anthropic  # noqa: WPS433
        except ImportError as e:
            raise RealLLMUnavailable("anthropic SDK 未安装") from e

        def _a(prompt, *, model=None, max_tokens=512, temperature=0.7):
            r = anthropic_adapter(prompt, model=model, max_tokens=max_tokens,
                                  temperature=temperature)
            _register(provider, r)
            return r["text"]
        return _a
    if provider == "openai":
        _require_env("OPENAI_API_KEY")
        try:
            import openai  # noqa: WPS433
        except ImportError as e:
            raise RealLLMUnavailable("openai SDK 未安装") from e

        def _o(prompt, *, model=None, max_tokens=512, temperature=0.7):
            r = openai_adapter(prompt, model=model, max_tokens=max_tokens,
                               temperature=temperature)
            _register(provider, r)
            return r["text"]
        return _o
    raise RealLLMUnavailable(f"未知 provider: {provider}")


_last_meta = {"provider": None, "usage": None, "latency_ms": None, "model": None}


def _register(provider: str, r: dict):
    _last_meta.update({"provider": provider, "usage": r.get("usage"),
                       "latency_ms": r.get("latency_ms"), "model": r.get("model")})


def last_metadata() -> dict:
    return dict(_last_meta)
