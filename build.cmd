@echo off
rem ============================================================
rem  Codex Switch - Windows build launcher
rem
rem  Usage:  double-click this file, or run it from a terminal
rem      build.cmd            rebuild (reuses PyInstaller caches)
rem      build.cmd -Clean     wipe caches first, full rebuild
rem
rem  Output: dist\CodexSwitch.exe
rem  Log:    build\build-YYYYMMDD-HHMMSS.log  (full PyInstaller output)
rem
rem  All real build logic lives in build.ps1; this file only adds a
rem  friendly front door and progress logging, so there is one place
rem  to change the build.
rem
rem  ASCII-only on purpose: cmd.exe reads batch files in the OEM code
rem  page, so non-ASCII text here can render as mojibake.
rem ============================================================
setlocal EnableExtensions
cd /d "%~dp0"

rem ---- 0. build log -------------------------------------------------
rem Timestamp comes from PowerShell: %DATE%/%TIME% are locale-dependent and
rem parsing them in batch breaks on non-English Windows.
if not exist "build" mkdir "build"
for /f "usebackq delims=" %%T in (`powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"`) do set "STAMP=%%T"
if "%STAMP%"=="" set "STAMP=manual"
set "LOG=build\build-%STAMP%.log"

echo.
echo [build] workspace : %CD%
echo [build] log file  : %LOG%
echo.

rem ---- 1. a running app locks dist\CodexSwitch.exe -------------------
tasklist /fi "imagename eq CodexSwitch.exe" /nh 2>nul | findstr /i "CodexSwitch.exe" >nul
if not errorlevel 1 (
    echo [build] CodexSwitch.exe is running and locks dist\CodexSwitch.exe.
    choice /c YN /n /m "[build] Close it automatically and continue? [Y/N] "
    if errorlevel 2 (
        echo [build] Aborted. Close CodexSwitch, then run build.cmd again.
        pause
        exit /b 1
    )
    taskkill /f /im CodexSwitch.exe >nul 2>nul
    echo [build] Closed it; waiting for the file lock to clear...
    timeout /t 3 /nobreak >nul
)

rem ---- 2. run the real build, capturing everything to the log --------
rem PYTHONUNBUFFERED makes PyInstaller emit progress immediately instead of
rem holding it in a block buffer until exit, which is what made a running
rem build look frozen.
set "PYTHONUNBUFFERED=1"
set "PYTHONIOENCODING=utf-8"

echo [build] started %DATE% %TIME%
echo [build] Build output is shown below and saved to the log file.
echo [build] Long silent stretches near the end are normal.
echo.

rem The log is written by the PowerShell side, not by redirecting cmd: this
rem project path contains Chinese characters, and cmd's native redirection
rem re-encodes them through the console code page, corrupting the log.
rem scripts\build-log.ps1 sets Console.OutputEncoding to UTF-8 first so the
rem native PyInstaller/pip output decodes correctly, then mirrors each line
rem to this console and to the log file as UTF-8.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build-log.ps1" -Script "%~dp0build.ps1" -Log "%LOG%" %*
set "CODE=%ERRORLEVEL%"

echo.
echo [build] finished %DATE% %TIME%  (exit %CODE%)

if not "%CODE%"=="0" (
    echo [build] FAILED. Full output: %LOG%
    pause
    exit /b %CODE%
)

if not exist "dist\CodexSwitch.exe" (
    echo [build] WARNING: reported success but dist\CodexSwitch.exe is missing.
    pause
    exit /b 1
)

for %%F in ("dist\CodexSwitch.exe") do echo [build] OK -^> dist\CodexSwitch.exe  %%~zF bytes  %%~tF
echo [build] Log: %LOG%
echo [build] Done.
pause
exit /b 0
