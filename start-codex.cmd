@echo off
setlocal EnableExtensions

for %%I in ("%~dp0.") do set "PROJECT_ROOT=%%~fI"
set "LAUNCHER=%PROJECT_ROOT%\.codex\bin\codex-profile.cmd"

if not exist "%LAUNCHER%" (
  echo Missing "%LAUNCHER%". Generate the project template first. 1^>^&2
  exit /b 1
)

call "%LAUNCHER%" %*
exit /b %errorlevel%
