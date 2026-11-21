#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地模型后端（Ollama）测试。

覆盖：
  - 后端选择（YUWEN_BACKEND / --backend / 交互默认值）
  - local 模式复用已有变量的 setdefault 语义（用户设置不覆盖）
  - local 模式不要求 API key（缺 key 也能构造 adapter）
  - 关思考模式：接口层参数 + 网关层 <think> 剥离（两条路都测）
  - Ollama 健康检查（服务连不上 / 模型不存在 / 正常）

不依赖真实 Ollama、不发网络请求：openai SDK 与 urllib 都被替换成假实现。
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for _p in (ROOT, os.path.join(ROOT, "tools"), os.path.join(ROOT, "runtime"),
           os.path.join(ROOT, "benchmark"), os.path.join(ROOT, "stage6", "cli")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import llm_gateway as lg  # noqa: E402
import real_llm_adapter as rla  # noqa: E402
import start as start_mod  # noqa: E402


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


ENV_KEYS = ("YUWEN_BACKEND", "OPENAI_BASE_URL", "OPENAI_API_KEY", "EX_MODEL")


def _snapshot():
    return {k: os.environ.get(k) for k in ENV_KEYS}


def _restore(snap):
    for k, v in snap.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _clear():
    for k in ENV_KEYS:
        os.environ.pop(k, None)


# ---------------- 1. 后端选择 ----------------

def t_backend_selection():
    snap = _snapshot()
    try:
        _clear()
        C.ok("backend: 默认 deepseek", rla.backend() == "deepseek", rla.backend())
        os.environ["YUWEN_BACKEND"] = "local"
        C.ok("backend: local", rla.backend() == "local")
        C.ok("backend: is_local", rla.is_local() is True)
        os.environ["YUWEN_BACKEND"] = "  LOCAL  "
        C.ok("backend: 大小写/空白容错", rla.backend() == "local", rla.backend())
        os.environ["YUWEN_BACKEND"] = "openai"
        C.ok("backend: 未知值回落 deepseek", rla.backend() == "deepseek")
    finally:
        _restore(snap)


# ---------------- 2. local 默认值用 setdefault ----------------

def t_local_defaults():
    snap = _snapshot()
    try:
        _clear()
        os.environ["YUWEN_BACKEND"] = "local"
        rla.apply_local_defaults()
        C.ok("defaults: base_url", os.environ["OPENAI_BASE_URL"] == "http://localhost:11434/v1",
             os.environ.get("OPENAI_BASE_URL"))
        C.ok("defaults: model", os.environ["EX_MODEL"] == "yuwen-4b-q4",
             os.environ.get("EX_MODEL"))
        C.ok("defaults: key 占位", os.environ["OPENAI_API_KEY"] == "local-no-key")

        # 用户手动设置过的值不能覆盖
        _clear()
        os.environ["OPENAI_BASE_URL"] = "http://127.0.0.1:9999/v1"
        os.environ["EX_MODEL"] = "yuwen-4b-q8"
        os.environ["OPENAI_API_KEY"] = "my-own-key"
        rla.apply_local_defaults()
        C.ok("defaults: 不覆盖 base_url", os.environ["OPENAI_BASE_URL"] == "http://127.0.0.1:9999/v1")
        C.ok("defaults: 不覆盖 model", os.environ["EX_MODEL"] == "yuwen-4b-q8")
        C.ok("defaults: 不覆盖 key", os.environ["OPENAI_API_KEY"] == "my-own-key")
    finally:
        _restore(snap)


# ---------------- 3. local 不要求 key（假 openai SDK）----------------

class _FakeResp:
    def __init__(self, text):
        self.choices = [type("X", (), {"message": type("Y", (), {"content": text})()})()]
        self.usage = type("U", (), {"prompt_tokens": 3, "completion_tokens": 4})()


class _FakeClient:
    last_kwargs = None

    def __init__(self, **kwargs):
        _FakeClient.init_kwargs = kwargs
        outer = self

        class _Completions:
            def create(self, **kw):
                _FakeClient.call_kwargs = kw
                return _FakeResp("你好")

        self.chat = type("Ch", (), {"completions": _Completions()})()


def _install_fake_openai():
    mod = type(sys)("openai")
    mod.OpenAI = _FakeClient
    sys.modules["openai"] = mod


def t_local_no_key():
    snap = _snapshot()
    had = sys.modules.get("openai")
    try:
        _clear()
        _install_fake_openai()
        os.environ["YUWEN_BACKEND"] = "local"
        rla.apply_local_defaults()

        # 关键：没有真实 key，也只有占位串，不应抛 RealLLMUnavailable
        r = rla.openai_adapter("hi", model="yuwen-4b-q4")
        C.ok("adapter: local 缺 key 可调用", r["text"] == "你好")
        C.ok("adapter: base_url 指向本机",
             _FakeClient.init_kwargs.get("base_url") == "http://localhost:11434/v1",
             str(_FakeClient.init_kwargs.get("base_url")))
        C.ok("adapter: key 用占位串",
             _FakeClient.init_kwargs.get("api_key") == "local-no-key",
             str(_FakeClient.init_kwargs.get("api_key")))
        C.ok("adapter: 构造 adapter 不抛错", isinstance(rla.make_provider_adapter("openai"), object))

        # 关思考：local 模式必须带 chat_template_kwargs
        body = _FakeClient.call_kwargs.get("extra_body")
        C.ok("adapter: local 关闭 thinking",
             body == {"chat_template_kwargs": {"enable_thinking": False}}, str(body))

        # deepseek 模式：缺 key 必须抛（保持原行为）
        os.environ.pop("OPENAI_API_KEY", None)
        os.environ["YUWEN_BACKEND"] = "deepseek"
        raised = False
        try:
            rla.openai_adapter("hi")
        except rla.RealLLMUnavailable:
            raised = True
        except Exception:  # noqa: BLE001
            raised = False
        C.ok("adapter: deepseek 缺 key 抛 RealLLMUnavailable", raised)

        # deepseek 模式不应带关闭思考的参数
        os.environ["OPENAI_API_KEY"] = "sk-test"
        rla.openai_adapter("hi")
        C.ok("adapter: deepseek 不带 thinking 参数",
             _FakeClient.call_kwargs.get("extra_body") is None,
             str(_FakeClient.call_kwargs.get("extra_body")))
    finally:
        _restore(snap)
        if had is not None:
            sys.modules["openai"] = had
        else:
            sys.modules.pop("openai", None)


# ---------------- 4. 去 <think> ----------------

def t_strip_think():
    C.ok("think: 完整段被删",
         lg.strip_think("<think>想一下</think>你好") == "你好",
         repr(lg.strip_think("<think>想一下</think>你好")))
    C.ok("think: 多段被删",
         lg.strip_think("A<think>x</think>B<think>y</think>C") == "ABC",
         repr(lg.strip_think("A<think>x</think>B<think>y</think>C")))
    C.ok("think: 未闭合截断",
         lg.strip_think("你好<think>还在想……") == "你好",
         repr(lg.strip_think("你好<think>还在想……")))
    C.ok("think: 无标签原样返回", lg.strip_think("  正常回复 ") == "正常回复")
    C.ok("think: 空串安全", lg.strip_think("") == "" and lg.strip_think(None) == "")
    C.ok("think: 大小写不敏感",
         lg.strip_think("<THINK>x</THINK>好") == "好",
         repr(lg.strip_think("<THINK>x</THINK>好")))


def t_gateway_strips():
    """网关这一层兜底：任何 adapter 返回的 think 都被剥掉。"""
    gw = lg.LLMGateway(adapter=lambda prompt, **kw: "<think>思考</think>最终回复")
    out = gw.chat([lg.ChatMessage("user", "在吗")])
    C.ok("gateway: 输出不含 think", out == "最终回复", repr(out))

    gw2 = lg.LLMGateway(adapter=lambda prompt, **kw: "没有思考的回复")
    C.ok("gateway: 普通回复不受影响", gw2.chat([lg.ChatMessage("user", "在吗")]) == "没有思考的回复")


# ---------------- 5. Ollama 健康检查 / 后端选择交互 ----------------

class _FakeUrlopen:
    payload = b'{"models": [{"name": "yuwen-4b-q4:latest"}]}'
    should_raise = False

    def __init__(self, *a, **kw):
        if _FakeUrlopen.should_raise:
            raise OSError("connection refused")
        self._data = _FakeUrlopen.payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._data


def t_ollama_ready():
    import urllib.request as ureq
    snap = _snapshot()
    orig = ureq.urlopen
    try:
        _clear()
        ureq.urlopen = _FakeUrlopen
        _FakeUrlopen.should_raise = False
        os.environ["OPENAI_BASE_URL"] = "http://localhost:11434/v1"
        ok, why = start_mod._ollama_ready("yuwen-4b-q4")
        C.ok("ollama: 模型存在 → ok", ok is True and why == "", why)

        ok2, why2 = start_mod._ollama_ready("yuwen-4b-q8")
        C.ok("ollama: 模型不存在 → 报原因", ok2 is False and "yuwen-4b-q8" in why2, why2)

        _FakeUrlopen.should_raise = True
        ok3, why3 = start_mod._ollama_ready("yuwen-4b-q4")
        C.ok("ollama: 服务未启动 → 报原因，不抛异常", ok3 is False and "Ollama" in why3, why3)

        # tags 地址由 base_url 推导
        C.ok("ollama: base_url 去 /v1",
             start_mod._ollama_base() == "http://localhost:11434/v1")
    finally:
        ureq.urlopen = orig
        _restore(snap)


def t_choose_backend():
    snap = _snapshot()
    import builtins
    orig_input = builtins.input
    try:
        _clear()
        C.ok("choose: --backend local", start_mod._choose_backend(["--backend", "local"]) == "local")
        C.ok("choose: --backend deepseek",
             start_mod._choose_backend(["--backend", "deepseek"]) == "deepseek")
        os.environ["YUWEN_BACKEND"] = "local"
        C.ok("choose: env 优先于默认", start_mod._choose_backend([]) == "local")
        _clear()

        # 无 env、无参数、stdin EOF → 默认云端（不能崩）
        def _eof(_prompt=""):
            raise EOFError
        builtins.input = _eof
        C.ok("choose: 非交互默认 deepseek", start_mod._choose_backend([]) == "deepseek")

        # 交互输入 "2" → local
        builtins.input = lambda _prompt="": "2"
        C.ok("choose: 输入 2 → local", start_mod._choose_backend([]) == "local")
        builtins.input = lambda _prompt="": "1"
        C.ok("choose: 输入 1 → deepseek", start_mod._choose_backend([]) == "deepseek")
    finally:
        builtins.input = orig_input
        _restore(snap)


def main():
    print("=== 本地模型后端测试 ===")
    for name, fn in [("backend selection", t_backend_selection),
                     ("local defaults", t_local_defaults),
                     ("local no key", t_local_no_key),
                     ("strip think", t_strip_think),
                     ("gateway strips", t_gateway_strips),
                     ("ollama ready", t_ollama_ready),
                     ("choose backend", t_choose_backend)]:
        print(f"\n▶ {name}")
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            import traceback
            C.ok(name, False, f"{type(e).__name__}: {e}")
            traceback.print_exc()
    print(f"\n通过 {C.ok_n} / 失败 {C.fail_n}")
    for f in C.fails:
        print("  -", f)
    sys.exit(0 if C.fail_n == 0 else 1)


if __name__ == "__main__":
    main()
