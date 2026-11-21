#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键跑完全部测试。

用法（项目根目录）：
    python run_tests.py              # 跑全部 28 个套件
    python run_tests.py -k runtime   # 只跑路径含 "runtime" 的套件
    python run_tests.py -v           # 失败时打印完整输出（默认打印末尾 20 行）

约定：
  - 只用标准库；用「当前解释器」(sys.executable) 逐个运行测试脚本，不依赖 pytest。
  - 所有路径相对本文件所在目录，不写死盘符，可在 Linux / Windows / macOS 运行。
  - 测试脚本均为脚本式（函数 t_xxx + 自建计数器），退出码非 0 即视为失败。
  - 若失败原因仅为缺少「可选依赖」(anthropic / PIL)，记为 SKIPPED，不计入失败。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time

# Windows 非中文 locale（如 cp1252）下，print 中文会抛 UnicodeEncodeError 并中断汇总。
# 强制把本进程的 stdout/stderr 切到 UTF-8；子进程另有 PYTHONIOENCODING 兜底。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.abspath(__file__))

# 28 个测试套件（相对 ROOT 的路径，统一用正斜杠，跨平台）
TEST_FILES = [
    # tools/ —— 解析、抽取、合并、构建、版本管理（8）
    "tools/test_chat_parsers.py",
    "tools/test_evidence_extractor.py",
    "tools/test_evidence_merge.py",
    "tools/test_import_pipeline.py",
    "tools/test_persona_memory_builder.py",
    "tools/test_resolve_bundle.py",
    "tools/test_skill_writer_v12.py",
    "tools/test_version_manager_v12.py",
    # runtime/ —— 运行时、纠正、持久化、检索（15）
    "runtime/tests/test_gateway_fallback_signal.py",
    "runtime/tests/test_instance_persistence.py",
    "runtime/tests/test_runtime.py",
    "runtime/tests/test_stage59_f1.py",
    "runtime/tests/test_stage59_f2f3.py",
    "runtime/tests/test_stage59_f4.py",
    "runtime/tests/test_stage59_f4_instance.py",
    "runtime/tests/test_stage59_f5.py",
    "runtime/tests/test_stage59_f5b_reopen.py",
    "runtime/tests/test_stage59_f5d.py",
    "runtime/tests/test_stage59_f5d_d3.py",
    "runtime/tests/test_stage59_f5e.py",
    "runtime/tests/test_stage59_f5f.py",
    "runtime/tests/test_stage59_f5f_phase2.py",
    "runtime/tests/test_stage59_f5f_phase3b.py",
    # benchmark/ —— 基准 harness、真实 adapter 配置（2）
    "benchmark/tests/test_benchmark_harness.py",
    "benchmark/tests/test_real_llm_adapter_config.py",
    # evaluation/ —— 评测框架（1）
    "evaluation/tests/test_eval_framework.py",
    # stage6/ —— Production Host、Pilot CLI（2）
    "stage6/host/test_production_host.py",
    "stage6/cli/test_mvp_cli.py",
]

# 允许「缺失即跳过」的可选依赖：模块名 -> pip 包名
OPTIONAL_MODULES = {
    "anthropic": "anthropic",
    "PIL": "Pillow",
}

SUMMARY_RE = re.compile(r"通过\s*(\d+)\s*/\s*失败\s*(\d+)")
MISSING_RE = re.compile(r"ModuleNotFoundError: No module named '([^']+)'")

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"

# 单个套件的上限；CI 上防止挂死（正常套件都在 3s 内）
PER_TEST_TIMEOUT_S = 600


def _env() -> dict:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    # 避免测试写入用户真实数据目录时被误判为用户数据：
    # 各测试自带临时目录，这里不覆盖，保持其在 tempfile 下运行。
    return env


def _classify(output: str, returncode: int) -> str:
    """返回 PASS / FAIL / SKIP。"""
    if returncode == 0:
        return PASS
    # 仅因缺少可选依赖而失败 -> SKIP
    missing = set(MISSING_RE.findall(output))
    if missing and missing <= set(OPTIONAL_MODULES):
        return SKIP
    return FAIL


def _counts(output: str) -> str:
    found = SUMMARY_RE.findall(output)
    if not found:
        return ""
    ok, bad = found[-1]
    return f"{ok} 断言通过 / {bad} 失败"


def _tail(text: str, lines: int = 20) -> str:
    rows = [r for r in text.replace("\r\n", "\n").split("\n")]
    return "\n".join(rows[-lines:]).rstrip()


def main(argv: list) -> int:
    verbose = "-v" in argv or "--verbose" in argv
    keyword = None
    if "-k" in argv:
        try:
            keyword = argv[argv.index("-k") + 1]
        except IndexError:
            print("用法：python run_tests.py [-k 关键词] [-v]", file=sys.stderr)
            return 2

    targets = [t for t in TEST_FILES if not keyword or keyword in t]
    if not targets:
        print(f"没有匹配 '{keyword}' 的测试文件", file=sys.stderr)
        return 2

    print(f"Python  : {sys.version.split()[0]}  ({sys.executable})")
    print(f"根目录  : {ROOT}")
    print(f"套件数  : {len(targets)}")
    print("=" * 78)

    results = []
    failures = []
    skipped = []
    started = time.time()

    for rel in targets:
        path = os.path.join(ROOT, *rel.split("/"))
        name = rel.rsplit("/", 1)[-1]
        if not os.path.isfile(path):
            status, detail, output = FAIL, "文件不存在", ""
        else:
            t0 = time.time()
            try:
                proc = subprocess.run(
                    [sys.executable, path],
                    cwd=ROOT,
                    env=_env(),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=PER_TEST_TIMEOUT_S,
                )
                output = (proc.stdout or "") + (proc.stderr or "")
                status = _classify(output, proc.returncode)
                detail = _counts(output) or (f"rc={proc.returncode}" if status == FAIL else "")
            except subprocess.TimeoutExpired as exc:
                output = ((exc.stdout or "") if isinstance(exc.stdout, str) else "") + \
                         f"\n[run_tests] 超时：>{PER_TEST_TIMEOUT_S}s 未结束"
                status, detail = FAIL, f"超时 >{PER_TEST_TIMEOUT_S}s"
            detail = f"{detail}  [{time.time() - t0:.1f}s]"

        mark = {PASS: "ok  ", FAIL: "FAIL", SKIP: "skip"}[status]
        print(f"[{mark}] {rel:<48} {detail}")

        results.append((rel, status, output))
        if status == FAIL:
            failures.append((rel, name, output))
        elif status == SKIP:
            skipped.append((rel, output))

    elapsed = time.time() - started
    n_pass = sum(1 for _, s, _ in results if s == PASS)
    n_fail = len(failures)
    n_skip = len(skipped)

    print("=" * 78)
    print(f"通过 {n_pass} / 失败 {n_fail} / 跳过 {n_skip}   （共 {len(results)} 个套件，"
          f"{elapsed:.1f}s）")

    if skipped:
        print("\n跳过的套件（仅缺可选依赖）：")
        for rel, output in skipped:
            missing = ", ".join(sorted(set(MISSING_RE.findall(output))))
            print(f"  - {rel}  缺少可选依赖：{missing}")

    if failures:
        print("\n失败的套件：")
        for rel, _name, _out in failures:
            print(f"  - {rel}")
        print("\n" + "-" * 78)
        for rel, _name, output in failures:
            print(f"\n### {rel} —— 末尾日志")
            print("-" * 78)
            print(_tail(output, 200 if verbose else 20))

    print()
    if n_fail:
        print(f"结果：失败（{n_fail} 个套件未通过）")
        return 1
    print("结果：全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
