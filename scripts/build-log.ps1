# Runs the real build script while mirroring every line to the console and to a
# UTF-8 log file.
#
# Why this exists instead of "build.ps1 *> log.txt" in build.cmd:
#   * cmd's native redirection re-encodes piped output through the console code
#     page, which corrupted this project's Chinese path ("编程" -> mojibake) in
#     the log.
#   * PowerShell's Tee-Object has no -Encoding in Windows PowerShell 5.1 and
#     defaults to UTF-16, producing a log that looks garbled in any UTF-8 reader.
# Setting Console.OutputEncoding to UTF-8 also makes native pip/PyInstaller
# output decode correctly instead of arriving as replacement characters.
#
# The build's own exit code is preserved so build.cmd can branch on failures.

# The build script's only option today is -Clean. It is declared as an explicit
# switch rather than gathered into a [string[]] and splatted, because array
# splatting passes "-Clean" as a positional *string*; the switch then silently
# stays false and a "full rebuild" would quietly reuse the cache instead.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Script,
    [Parameter(Mandatory = $true)][string]$Log,
    [switch]$Clean
)

$ErrorActionPreference = 'Continue'

$env:PYTHONUNBUFFERED = '1'
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$logDir = Split-Path -Parent $Log
if ($logDir -and -not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}
# Start from a clean file so a previous run can never be mistaken for this one.
Set-Content -Path $Log -Value "" -Encoding UTF8

if (-not (Test-Path $Script)) {
    $message = "build script not found: $Script"
    Write-Host "[build] ERROR: $message"
    Add-Content -Path $Log -Value $message -Encoding UTF8
    exit 2
}

# The build's progress lines come from Write-Host, which writes to the
# information stream (6) rather than stdout. Redirecting only 2>&1 would drop
# every "Building EXE ..." message from the log, so 6>&1 is merged in too.
& $Script -Clean:$Clean 6>&1 2>&1 | ForEach-Object {
    $line = $_.ToString()
    Write-Host $line
    Add-Content -Path $Log -Value $line -Encoding UTF8
}

# $LASTEXITCODE carries the child script's exit code; it stays unset only when
# the build never ran, which the not-found guard above already handled.
if ($null -ne $LASTEXITCODE) {
    exit $LASTEXITCODE
}
exit 0
