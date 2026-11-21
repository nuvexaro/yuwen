@echo off
rem Stage 6.3 一键启动（Windows 普通用户入口）。
rem 运行 start.py：它会在「当前进程内存」里处理 API Key（不写盘、不回显、不打印），
rem 自动配置 provider/model，然后进入 MVP CLI。
rem 若已在系统环境变量配好 DEEPSEEK_API，则不会重复询问。
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
    echo 未找到 python。请先安装 Python 3.10+ 并勾选 "Add to PATH"。
    pause
    exit /b 1
)
python start.py %*
if errorlevel 1 pause
