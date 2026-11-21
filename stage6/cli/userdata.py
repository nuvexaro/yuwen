#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""User data root（Non-Frozen Product Surface / Distribution Layer）。

正式 EXE：用户运行时数据必须落在用户可写目录，不能写 PyInstaller bundle/_MEIPASS/_internal，
也不依赖 EXE 所在目录可写。

根目录优先级：
  1. 环境变量 EX_DATA_ROOT（测试/开发可覆盖）
  2. %USERPROFILE%\\.ex_ai\\   （Windows）
  3. ~/.ex_ai                  （非 Windows 回退）

子目录：exes / sessions / pilot_data
不改变 persona_memory schema/内容语义；只改变 Product Surface 提供的数据根目录。
"""

from __future__ import annotations

import os
import sys


def resolve_sample_path() -> str | None:
    """定位内置示例 ChatImport（sample_messages.json）。

    打包 EXE：sample_messages.json 作为 packaged data 放在 onedir 根（EXE 旁 /
    _MEIPASS / cwd），运行时从那里读，绝不依赖开发环境 evaluation/ 路径。
    候选顺序：
      1. 环境变量 EX_SAMPLE_IMPORT（显式指定）
      2. PyInstaller _MEIPASS（onefile/onedir 资源根）
      3. sys.executable 所在目录（onedir 根，EXE 旁）
      4. 当前工作目录
      5. 用户数据根（.ex_ai）
      6. 开发模式：仓库 evaluation/dataset/case_001/messages.json
    """
    exe_dir = os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, "frozen", False) else None
    meipass = getattr(sys, "_MEIPASS", None)
    cands = [
        os.environ.get("EX_SAMPLE_IMPORT"),
        # spec 以原文件名 messages.json 打进 _internal；build.bat 另以 sample_messages.json 拷到 dist 根
        os.path.join(meipass, "sample_messages.json") if meipass else None,
        os.path.join(meipass, "messages.json") if meipass else None,
        os.path.join(exe_dir, "sample_messages.json") if exe_dir else None,
        os.path.join(exe_dir, "messages.json") if exe_dir else None,
        os.path.join(os.getcwd(), "sample_messages.json"),
        os.path.join(os.getcwd(), "messages.json"),
        os.path.join(user_data_root(), "sample_messages.json"),
    ]
    for c in cands:
        if c and os.path.exists(c):
            return c
    # 开发模式 fallback：仓库示例
    dev = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "..", "..", "evaluation", "dataset", "case_001", "messages.json"))
    return dev if os.path.exists(dev) else None


def user_data_root() -> str:
    """返回用户可写数据根目录（自动创建）。"""
    root = os.environ.get("EX_DATA_ROOT")
    if not root:
        profile = os.environ.get("USERPROFILE") or os.path.expanduser("~")
        root = os.path.join(profile, ".ex_ai")
    os.makedirs(root, exist_ok=True)
    return root


def exes_dir() -> str:
    d = os.path.join(user_data_root(), "exes")
    os.makedirs(d, exist_ok=True)
    return d


def sessions_dir() -> str:
    d = os.path.join(user_data_root(), "sessions")
    os.makedirs(d, exist_ok=True)
    return d


def pilot_data_dir() -> str:
    d = os.path.join(user_data_root(), "pilot_data")
    os.makedirs(d, exist_ok=True)
    return d
