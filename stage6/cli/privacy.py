#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 6.3 P3 — Privacy / redaction helpers（Non-Frozen）。

职责：日志/输出脱敏——不打印 API key、不打印聊天正文进入日志。
delete_ex_data 由 mvp_cli.cmd_delete 负责（清 slug + sessions + versions）。
"""

from __future__ import annotations

import os
import re

# 疑似 key / secret 模式（sk-… / 长 hex / api token）
_KEY_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(?i)(api[_-]?key|secret|token)\s*[=:]\s*\S+"),
    re.compile(r"[A-Za-z0-9]{32,}"),
]


def redact(text: str) -> str:
    """把疑似敏感串替换为 [REDACTED]。用于日志/错误输出，不用于正常用户消息。"""
    out = text
    for p in _KEY_PATTERNS:
        out = p.sub("[REDACTED]", out)
    return out


def log_redacted(event: str, data: dict) -> str:
    """生成脱敏日志行：只记事件类型与安全字段，不含 key / 正文。"""
    safe = {k: v for k, v in data.items()
            if k not in ("assistant", "user", "message", "chat", "content", "key", "api_key")}
    return f"[{event}] {redact(str(safe))}"


def api_key_from_env() -> bool:
    """确认 key 仅来自 env；返回是否存在（不打印值）。"""
    return bool(os.environ.get("DEEPSEEK_API") or os.environ.get("OPENAI_API_KEY"))
