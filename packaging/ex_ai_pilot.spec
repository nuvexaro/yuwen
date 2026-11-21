# -*- mode: python ; coding: utf-8 -*-
# Stage 6.3 EXE 打包 spec（onedir）。Non-Frozen Distribution Layer。
# 用法见 build.bat；schema 等资源在 build.bat 中复制到 dist 根（与 __file__-相对解析一致）。

import os

repo = os.path.abspath(os.path.join(os.getcwd()))
cli = os.path.join(repo, "stage6", "cli")
host = os.path.join(repo, "stage6", "host")

a = Analysis(
    [os.path.join(cli, "start.py")],
    pathex=[repo, os.path.join(repo, "tools"), os.path.join(repo, "runtime"),
            os.path.join(repo, "evaluation"), os.path.join(repo, "benchmark"),
            cli, host],
    binaries=[],
    datas=[
        # 内置示例正式打进包（_MEIPASS/sample_messages.json），运行时经
        # userdata.resolve_sample_path() 定位；schema 仍由 build.bat 复制到 dist 根。
        (os.path.join(repo, "evaluation", "dataset", "case_001", "messages.json"),
         "."),  # 落在 <bundle>/sample_messages.json
    ],
    hiddenimports=[
        "persona_runtime", "persona_loader", "instance_persistence", "production_host",
        "session_store", "context_assembly", "memory_retrieval", "reality_boundary",
        "persona_constraints", "llm_gateway", "memory_proposal", "correction_runtime",
        "correction_conflicts", "correction_export", "correction_longterm_projection",
        "mock_responders", "privacy", "mvp_cli", "mvp_session", "pilot_recorder",
        "userdata", "skill_writer_v12", "version_manager", "eval_runner", "real_llm_adapter",
        "chat_parser_common", "evidence_extractor", "evidence_merge", "resolve_bundle",
        "import_pipeline", "persona_memory_builder", "wechat_parser", "qq_parser",
        "eval_schema", "eval_llm_mocks",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["torch", "tensorboard", "PIL", "matplotlib", "numpy", "pandas", "scipy",
              "sklearn", "cv2", "anthropic"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="ex-ai-pilot",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="ex-ai-pilot",
)
