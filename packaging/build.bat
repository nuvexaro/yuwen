@echo off
rem Stage 6.3 EXE 正式打包（onedir）。Non-Frozen Distribution Layer。
rem 用法：在项目根 packaging\ 下运行  build.bat
setlocal
cd /d "%~dp0.."

echo === [1/4] PyInstaller onedir build ===
python -m PyInstaller --noconfirm --log-level=WARN packaging\ex_ai_pilot.spec --distpath dist_pkg\dist --workpath dist_pkg\build
if errorlevel 1 ( echo PyInstaller 失败 & exit /b 1 )

set DIST=dist_pkg\dist\ex-ai-pilot

echo === [2/4] copy schema.json to dist root (module __file__-relative) ===
copy /y persona_memory.schema.json "%DIST%\" >nul
copy /y message.schema.json "%DIST%\" >nul
copy /y evidence_candidate.schema.json "%DIST%\" >nul
copy /y merge_group.schema.json "%DIST%\" >nul
copy /y resolved_evidence_bundle.schema.json "%DIST%\" >nul
if errorlevel 1 ( echo schema copy 失败 & exit /b 1 )

echo === [3/4] copy sample ChatImport to dist root ===
copy /y evaluation\dataset\case_001\messages.json "%DIST%\sample_messages.json" >nul

echo === [4/4] zip ===
powershell -Command "Compress-Archive -Path '%DIST%\*' -DestinationPath 'dist_pkg\ex-ai-pilot.zip' -Force"
if errorlevel 1 ( echo zip 失败(可忽略，dist 仍可用) )

echo.
echo 完成。产物：
echo   EXE 目录: %DIST%
echo   ZIP:      dist_pkg\ex-ai-pilot.zip
echo 用户数据将写到: %USERPROFILE%\.ex_ai\
endlocal
