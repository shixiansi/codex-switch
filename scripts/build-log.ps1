# Runs the real build script while streaming every line to the console and to a
# UTF-8 log file, then exits with the build's own exit code.
#
# Why a wrapper at all instead of "build.ps1 *> log.txt":
#   * cmd's own ">" redirection cannot both show output and save it.
#   * Tee-Object has no -Encoding in Windows PowerShell 5.1 and writes UTF-16,
#     so the log reads as mojibake/NUL bytes in any UTF-8 viewer.
#
# Why the child runs in a *separate process*, rather than
# "& $Script 6>&1 2>&1 | ForEach-Object ..." in this one:
#   PowerShell 5.1 turns a native command's stderr into an ErrorRecord as soon
#   as it is merged with 2>&1. build.ps1 runs with $ErrorActionPreference='Stop'
#   (deliberately: a build error must abort), so the first line pip writes to
#   stderr - which it does routinely - became a terminating NativeCommandError
#   and killed the build. Redirecting at the process boundary keeps the child's
#   error semantics intact while still capturing everything here.
#
# Why System.Diagnostics.Process and not Start-Process -PassThru:
#   Start-Process returned an EMPTY ExitCode in testing on this machine, which
#   would have reported every failed build as a success. The .NET API returns
#   the real code (verified 0/1/7).
#
# Why the child redirects into files instead of pipes:
#   Reading one pipe synchronously deadlocks once the other pipe's buffer fills,
#   which would hang a chatty build forever. Files have no such limit, and this
#   wrapper tails them so a long silent phase stays visibly alive.
#
# The child is told to emit UTF-8 so the bytes decode correctly even though this
# project's path contains Chinese characters ("编程").

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Script,
    [Parameter(Mandatory = $true)][string]$Log,
    # Declared explicitly rather than splatting an array: array splatting passes
    # "-Clean" as a positional string, so the switch would silently stay false
    # and a requested full rebuild would quietly reuse the cache.
    [switch]$Clean
)

$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# Set here rather than trusting the caller: PYTHONIOENCODING makes pip and
# PyInstaller emit UTF-8 (they would otherwise use the locale code page, so this
# project's Chinese path turned into mojibake in the log), and PYTHONUNBUFFERED
# stops their progress from sitting in a block buffer until exit.
$env:PYTHONUNBUFFERED = '1'
$env:PYTHONIOENCODING = 'utf-8'

$logDir = Split-Path -Parent $Log
if ($logDir -and -not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}
Set-Content -Path $Log -Value "" -Encoding UTF8

if (-not (Test-Path $Script)) {
    $message = "[build] ERROR: build script not found: $Script"
    Write-Host $message
    Add-Content -Path $Log -Value $message -Encoding UTF8
    exit 2
}

$tempRoot = [System.IO.Path]::GetTempPath()
$tag = [guid]::NewGuid().ToString('N')
$outFile = Join-Path $tempRoot "codex-build-out-$tag.txt"
$errFile = Join-Path $tempRoot "codex-build-err-$tag.txt"
$launcher = Join-Path $tempRoot "codex-build-run-$tag.ps1"
$cleanArg = if ($Clean) { ' -Clean' } else { '' }

# A tiny generated launcher rather than "-Command" with the build path inlined:
# the path contains Chinese characters and quotes, and nesting those inside the
# cmd.exe command line is where quoting bugs hide. A file has no such problem.
$launcherBody = @"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
& '$Script'$cleanArg
exit `$LASTEXITCODE
"@
Set-Content -Path $launcher -Value $launcherBody -Encoding UTF8

# cmd.exe owns the redirection, so the child needs no pipe plumbing and keeps
# its own $ErrorActionPreference semantics.
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = 'cmd.exe'
$psi.Arguments = '/c powershell.exe -NoProfile -ExecutionPolicy Bypass -File "' + $launcher + '" > "' + $outFile + '" 2> "' + $errFile + '"'
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true
$psi.WorkingDirectory = (Get-Location).Path

$process = New-Object System.Diagnostics.Process
$process.StartInfo = $psi
[void]$process.Start()

$seen = @{}
foreach ($f in @($outFile, $errFile)) { $seen[$f] = 0 }

function Write-PendingLines {
    param([string]$Path, [hashtable]$Seen, [string]$LogPath)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    # The child writes UTF-8; any other reading encoding mangles the Chinese
    # project path.
    $lines = @(Get-Content -LiteralPath $Path -Encoding UTF8 -ErrorAction SilentlyContinue)
    for ($i = $Seen[$Path]; $i -lt $lines.Count; $i++) {
        $line = $lines[$i]
        Write-Host $line
        Add-Content -Path $LogPath -Value $line -Encoding UTF8
    }
    $Seen[$Path] = $lines.Count
}

while (-not $process.WaitForExit(200)) {
    Write-PendingLines -Path $outFile -Seen $seen -LogPath $Log
    Write-PendingLines -Path $errFile -Seen $seen -LogPath $Log
}

# Drain whatever landed between the last poll and exit.
Write-PendingLines -Path $outFile -Seen $seen -LogPath $Log
Write-PendingLines -Path $errFile -Seen $seen -LogPath $Log

$exitCode = $process.ExitCode
$process.Dispose()
Remove-Item -LiteralPath $outFile, $errFile, $launcher -Force -ErrorAction SilentlyContinue

exit $exitCode
