param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$venv = Join-Path $root ".venv"
$hostPython = "python"
$buildRequirements = Join-Path $root "requirements-build.txt"
$distExe = Join-Path $root "dist\CodexSwitch.exe"
$specPath = Join-Path $root "CodexSwitch.spec"
$warnFile = Join-Path $root "build\CodexSwitch\warn-CodexSwitch.txt"

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

function Ensure-VenvPip {
    param(
        [string]$PythonExe
    )

    & $PythonExe -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('pip') else 1)"
    if ($LASTEXITCODE -eq 0) {
        return
    }

    Write-Host "pip not found in .venv, bootstrapping with ensurepip..."
    Invoke-Step @($PythonExe, "-m", "ensurepip", "--upgrade")
}

function Normalize-TkEnvironment {
    param(
        [string]$PythonExe
    )

    $basePrefix = (& $PythonExe -c "import sys; print(sys.base_prefix)").Trim()
    if (-not $basePrefix) {
        throw "Unable to determine sys.base_prefix for the build Python."
    }

    $expectedDirs = @{
        "TCL_LIBRARY" = @("tcl\\tcl8.6", "tcl\\tcl8")
        "TK_LIBRARY"  = @("tcl\\tk8.6")
    }

    foreach ($envKey in $expectedDirs.Keys) {
        $currentValue = [Environment]::GetEnvironmentVariable($envKey, "Process")
        if ($currentValue -and (Test-Path $currentValue)) {
            continue
        }

        if ($currentValue) {
            Remove-Item "Env:$envKey" -ErrorAction SilentlyContinue
        }

        foreach ($relativePath in $expectedDirs[$envKey]) {
            $candidate = Join-Path $basePrefix $relativePath
            if (Test-Path $candidate) {
                Set-Item "Env:$envKey" $candidate
                break
            }
        }
    }
}

function Assert-TkinterAvailable {
    param(
        [string]$PythonExe
    )

    & $PythonExe -c "import _tkinter, tkinter"
    if ($LASTEXITCODE -ne 0) {
        throw "The build Python does not have tkinter available. Install a Python distribution with Tk support, then rebuild."
    }
}

function Assert-NoMissingTkinterWarning {
    param(
        [string]$WarnPath
    )

    if (-not (Test-Path $WarnPath)) {
        return
    }

    $warnContent = Get-Content $WarnPath -Raw
    if (
        $warnContent -match "missing module named tkinter" -or
        $warnContent -match "missing module named _tkinter" -or
        $warnContent -match "tkinter installation is broken"
    ) {
        throw "PyInstaller reported tkinter as missing. Build aborted because the packaged app would fail at runtime.`nSee: $WarnPath"
    }
}

function Assert-BuildOutputUnlocked {
    param(
        [string]$OutputPath
    )

    if (-not (Test-Path $OutputPath)) {
        return
    }

    $running = Get-Process | Where-Object {
        try {
            $_.Path -eq $OutputPath
        } catch {
            $false
        }
    }

    if ($running) {
        $processList = ($running | ForEach-Object { "$($_.ProcessName) (PID $($_.Id))" }) -join ", "
        throw "Build output is currently in use: $OutputPath`nClose these processes and run build.ps1 again: $processList"
    }
}

Ensure-VenvPip -PythonExe $python
Normalize-TkEnvironment -PythonExe $python
Assert-TkinterAvailable -PythonExe $python
Assert-BuildOutputUnlocked -OutputPath $distExe

Invoke-Step @(
    $python, "-m", "pip", "install",
    "--default-timeout", "600",
    "--prefer-binary",
    "-r", $buildRequirements
)

$args = @(
    "-m", "PyInstaller",
    "--noconfirm",
    $specPath
)

if ($Clean) {
    $args = @("-m", "PyInstaller", "--noconfirm", "--clean", $specPath)
}

Invoke-Step (@($python) + $args)
Assert-NoMissingTkinterWarning -WarnPath $warnFile

Write-Host ""
Write-Host "Build finished: dist\CodexSwitch.exe"
