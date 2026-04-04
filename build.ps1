param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$venv = Join-Path $root ".venv"
$hostPython = "python"

function Invoke-Step {
    param(
        [string[]]$Command
    )

    & $Command[0] $Command[1..($Command.Length - 1)]
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $($Command -join ' ')"
    }
}

if (-not (Test-Path $venv)) {
    Invoke-Step @($hostPython, "-m", "venv", $venv)
}

$python = Join-Path $venv "Scripts\python.exe"

Invoke-Step @(
    $hostPython, "-m", "pip", "--python", $python, "install",
    "--default-timeout", "600",
    "--prefer-binary",
    "pyinstaller==6.19.0"
)

$args = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--onefile",
    "--windowed",
    "--name", "CodexSwitch",
    "main.py"
)

if ($Clean) {
    $args += "--clean"
}

Invoke-Step (@($python) + $args)

Write-Host ""
Write-Host "Build finished: dist\CodexSwitch.exe"
