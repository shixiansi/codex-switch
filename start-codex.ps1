$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$envFile = Join-Path $projectRoot '.codex\local.env'
$codexHome = Join-Path $projectRoot '.codex\home'
$userDataDir = Join-Path $env:LOCALAPPDATA 'Code-codex'
$settingsDir = Join-Path $userDataDir 'User'
$settingsPath = Join-Path $settingsDir 'settings.json'

if (-not (Test-Path -LiteralPath $envFile)) {
  throw "Missing $envFile. Copy .codex\local.env.example to .codex\local.env first."
}

if (-not (Test-Path -LiteralPath (Join-Path $codexHome 'config.toml'))) {
  throw "Missing $codexHome\config.toml."
}

$codeCli = Get-Command code.cmd -ErrorAction SilentlyContinue
if (-not $codeCli) {
  $codeCli = Get-Command code -ErrorAction SilentlyContinue | Where-Object { $_.Source -like '*.cmd' } | Select-Object -First 1
}
if (-not $codeCli) {
  throw "VS Code CLI 'code.cmd' was not found. Make sure the VS Code shell command is installed."
}

New-Item -ItemType Directory -Force -Path $settingsDir | Out-Null

$settings = [pscustomobject]@{}
if (Test-Path -LiteralPath $settingsPath) {
  $raw = Get-Content -LiteralPath $settingsPath -Raw
  $raw = $raw.TrimStart([char]0xFEFF)
  if ($raw.Trim()) {
    try {
      $settings = $raw | ConvertFrom-Json
    } catch {
      $settings = [pscustomobject]@{}
    }
  }
}

if ($settings.PSObject.Properties['chatgpt.cliExecutable']) {
  $settings.PSObject.Properties.Remove('chatgpt.cliExecutable')
}

$json = $settings | ConvertTo-Json -Depth 20
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($settingsPath, $json, $utf8NoBom)

Get-Content -LiteralPath $envFile | ForEach-Object {
  if ($_ -match '^\s*([^#=]+?)\s*=\s*(.*)\s*$') {
    [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), 'Process')
  }
}

[Environment]::SetEnvironmentVariable('CODEX_HOME', $codexHome, 'Process')

Start-Process -FilePath $codeCli.Source -ArgumentList @(
  $projectRoot,
  '--new-window',
  '--user-data-dir', $userDataDir
)
