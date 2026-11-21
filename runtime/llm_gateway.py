#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LLM Gateway（供应商无关）。

Runtime 核心只依赖 gateway.chat(...)。支持 mock / adapter / timeout / retry /
max_tokens / temperature / usage / latency / model metadata。
mock 模式供 5.6 评测与 determinism 测试。
"""

from __future__ import annotations

import re
import time
from typing import Callable, List, Optional

DEFAULT_TIMEOUT_S = 30
DEFAULT_RETRY = 1

# 本地模型（Qwen 系列）可能带 思考过程，个别版本关不掉。
# 网关是最后一道关：无论哪个 adapter，输出都过一遍这里。
_THINK_RE = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.S | re.I)
_THINK_OPEN_RE = re.compile(r"<think\b[^>]*>.*\Z", re.S | re.I)


def strip_think(text: str) -> str:
    """去掉 <think>...</think> 整段；未闭合的 <think> 从该处截断。"""
    if not text:
        return ""
    out = _THINK_RE.sub("", text)
    out = _THINK_OPEN_RE.sub("", out)
    return out.strip()


class GatewayError(Exception):
    pass


class ChatMessage:
    def __init__(self, role: str, content: str):
        self.role = role
        self.content = content

    def as_dict(self):
        return {"role": self.role, "content": self.content}


class LLMGateway:
    """最小 gateway：adapter 可注入。adapter(prompt, *, model, max_tokens, temperature) -> str。"""

    def __init__(self, adapter: Optional[Callable] = None, *, model: str = "mock",
                 timeout: float = DEFAULT_TIMEOUT_S, retry: int = DEFAULT_RETRY):
        self.adapter = adapter or _mock_adapter
        self.model = model
        self.timeout = timeout
        self.retry = retry
        self.usage = {"calls": 0, "tokens": 0}
        self.latency_ms = 0.0

    def chat(self, messages: List[ChatMessage], *, model: Optional[str] = None,
             max_tokens: int = 512, temperature: float = 0.7) -> str:
        """调用 LLM。异常 → 重试 retry 次 → 抛 GatewayError。"""
        prompt = _messages_to_text(messages)
        mdl = model or self.model
        last_exc = None
        for attempt in range(self.retry + 1):
            t0 = time.time()
            try:
                out = self.adapter(prompt, model=mdl, max_tokens=max_tokens,
                                   temperature=temperature)
                self.usage["calls"] += 1
                self.usage["tokens"] += max_tokens
                self.latency_ms = (time.time() - t0) * 1000
                return strip_think(out) if isinstance(out, str) else out
            except Exception as e:  # noqa: BLE001
                last_exc = e
                time.sleep(0.05 * (attempt + 1))
        raise GatewayError(f"LLM 调用失败: {last_exc}")

    @property
    def metadata(self) -> dict:
        return {"model": self.model, "usage": dict(self.usage),
                "latency_ms": round(self.latency_ms, 1), "timeout": self.timeout}


MOCK_REPLY = "[离线模式] 这是测试回复，未连接真实模型。"


def _mock_adapter(prompt: str, *, model=None, max_tokens=None, temperature=None) -> str:
    """默认 mock：返回固定占位回复，绝不回显 prompt（避免人格设定泄漏到回复里）。

    只用于验证管道连通性，不代表任何回复质量；需要更像人话的确定性回复时，
    注入 mock_responders.simple_responder 或自定义 adapter。
    """
    return MOCK_REPLY


def _messages_to_text(messages: List[ChatMessage]) -> str:
    return "\n".join(f"<{m.role}>{m.content}</{m.role}>" for m in messages)
