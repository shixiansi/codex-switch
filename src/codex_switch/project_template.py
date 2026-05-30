from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import shutil
import sys
import tomllib

from codex_switch.codex_config import (
    PROJECT_ENV_KEY,
    PROJECT_PROVIDER_ID,
    dumps_toml,
    parse_mcp_servers_toml,
    render_mcp_servers_json,
    render_mcp_servers_toml,
    render_project_repo_config,
    render_project_runtime_config,
    scope_mcp_servers_to_project,
    timestamp_label,
)
from codex_switch.models import Profile
from codex_switch.resources import asset_path


CODEX_SCRIPT_DIRNAME = "codex_scripts"
CLAUDE_BASE_URL_ENV_KEY = "ANTHROPIC_BASE_URL"
CLAUDE_API_KEY_ENV_KEY = "ANTHROPIC_API_KEY"
CLAUDE_MODEL_ENV_KEY = "ANTHROPIC_MODEL"
CLAUDE_FALLBACK_MODEL_ENV_KEY = "ANTHROPIC_DEFAULT_HAIKU_MODEL"
GITIGNORE_MANAGED_BEGIN = "# >>> codex-switch managed ignores >>>"
GITIGNORE_MANAGED_END = "# <<< codex-switch managed ignores <<<"
MANAGED_GITIGNORE_RULES = (
    f"{CODEX_SCRIPT_DIRNAME}/",
)
MANAGED_TEMPLATE_FILES = (
    "AGENTS.md",
    "CLAUDE.md",
    ".mcp.json",
    f"{CODEX_SCRIPT_DIRNAME}/start-codex.ps1",
    f"{CODEX_SCRIPT_DIRNAME}/start-codex.cmd",
    f"{CODEX_SCRIPT_DIRNAME}/codex-profile.cmd",
    ".codex/config.toml",
    ".codex/local.env",
    ".codex/local.env.example",
    ".codex/home/config.toml",
    ".codex/home/AGENTS.md",
    ".claude/settings.local.json",
)
GENERATED_TEMPLATE_FILES = MANAGED_TEMPLATE_FILES + (".gitignore",)
BACKUP_TEMPLATE_FILES = MANAGED_TEMPLATE_FILES + (".gitignore",)


def load_default_agents_doc_text() -> str:
    return asset_path("AGENTS.md").read_text(encoding="utf-8")


def upsert_managed_gitignore_block(existing_text: str) -> str:
    normalized = existing_text.replace("\r\n", "\n")
    managed_block = "\n".join(
        (
            GITIGNORE_MANAGED_BEGIN,
            *MANAGED_GITIGNORE_RULES,
            GITIGNORE_MANAGED_END,
        )
    )
    start = normalized.find(GITIGNORE_MANAGED_BEGIN)
    end = normalized.find(GITIGNORE_MANAGED_END)
    if start != -1 and end != -1 and end >= start:
        end += len(GITIGNORE_MANAGED_END)
        prefix = normalized[:start].rstrip("\n")
        suffix = normalized[end:].lstrip("\n")
        parts = [part for part in (prefix, managed_block, suffix) if part]
        return "\n\n".join(parts).rstrip("\n") + "\n"

    base = normalized.rstrip("\n")
    parts = [part for part in (base, managed_block) if part]
    return "\n\n".join(parts).rstrip("\n") + "\n"


@dataclass
class ProjectTemplateResult:
    generated_paths: list[Path]
    backup_dir: Path
    project_root: Path
    start_script_path: Path


@dataclass
class ProjectTemplateStatus:
    generated_paths: list[Path]
    backup_dir: Path | None
    project_root: Path
    start_script_path: Path


class ProjectTemplateService:
    def sync_api_binding(self, project_root: Path, profile: Profile) -> list[Path]:
        project_root = project_root.resolve()
        repo_config_path = project_root / ".codex" / "config.toml"
        runtime_config_path = project_root / ".codex" / "home" / "config.toml"
        env_path = project_root / ".codex" / "local.env"
        updated_paths: list[Path] = []

        if repo_config_path.exists():
            with repo_config_path.open("rb") as handle:
                config = tomllib.load(handle)
            config["model"] = profile.codex_display_model
            config["review_model"] = profile.codex_display_model
            repo_config_path.write_text(dumps_toml(config), encoding="utf-8")
            updated_paths.append(repo_config_path)

        if runtime_config_path.exists():
            with runtime_config_path.open("rb") as handle:
                config = tomllib.load(handle)
            config["model"] = profile.codex_display_model
            config["review_model"] = profile.codex_display_model
            providers = config.setdefault("model_providers", {})
            provider = providers.setdefault(PROJECT_PROVIDER_ID, {})
            provider.setdefault("name", profile.provider_name)
            provider["base_url"] = profile.base_url.rstrip("/")
            provider["wire_api"] = profile.wire_api
            provider["env_key"] = PROJECT_ENV_KEY
            provider.pop("requires_openai_auth", None)
            runtime_config_path.write_text(dumps_toml(config), encoding="utf-8")
            updated_paths.append(runtime_config_path)

        if repo_config_path.exists() or runtime_config_path.exists() or env_path.exists():
            env_path.parent.mkdir(parents=True, exist_ok=True)
            existing_env = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
            env_path.write_text(self._render_local_env_with_key(existing_env, profile.api_key), encoding="utf-8")
            updated_paths.append(env_path)

        return updated_paths

    def sync_claude_binding(self, project_root: Path, profile: Profile) -> list[Path]:
        project_root = project_root.resolve()
        settings_path = project_root / ".claude" / "settings.local.json"
        payload = self._load_claude_settings_payload(settings_path)
        payload = self._render_claude_settings_payload(profile, payload)

        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return [settings_path]

    def generate(
        self,
        project_root: Path,
        profile: Profile,
        *,
        global_mcp_toml: str = "",
        project_mcp_toml: str = "",
        agents_doc_text: str | None = None,
        claude_profile: Profile | None = None,
    ) -> ProjectTemplateResult:
        project_root = project_root.resolve()
        codex_dir = project_root / ".codex"
        backup_root = codex_dir / "template-backups"

        codex_dir.mkdir(parents=True, exist_ok=True)
        backup_root.mkdir(parents=True, exist_ok=True)

        backup_dir = self._backup_managed_files(project_root, backup_root)
        files = self._render_files(
            project_root,
            profile,
            global_mcp_toml=global_mcp_toml,
            project_mcp_toml=project_mcp_toml,
            agents_doc_text=agents_doc_text,
            claude_profile=claude_profile,
        )

        generated_paths: list[Path] = []
        for relative_path, content in files.items():
            target = project_root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            generated_paths.append(target)

        return ProjectTemplateResult(
            generated_paths=generated_paths,
            backup_dir=backup_dir,
            project_root=project_root,
            start_script_path=project_root / CODEX_SCRIPT_DIRNAME / "start-codex.ps1",
        )

    def generate_claude_template(
        self,
        project_root: Path,
        profile: Profile,
        *,
        project_mcp_toml: str = "",
        agents_doc_text: str | None = None,
    ) -> ProjectTemplateResult:
        project_root = project_root.resolve()
        backup_root = project_root / ".claude" / "template-backups"
        backup_root.mkdir(parents=True, exist_ok=True)

        backup_dir = self._backup_managed_files(project_root, backup_root)
        files = self._render_claude_files(
            project_root,
            project_mcp_toml=project_mcp_toml,
            agents_doc_text=agents_doc_text,
            profile=profile,
        )

        generated_paths: list[Path] = []
        for relative_path, content in files.items():
            target = project_root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            generated_paths.append(target)

        return ProjectTemplateResult(
            generated_paths=generated_paths,
            backup_dir=backup_dir,
            project_root=project_root,
            start_script_path=project_root / CODEX_SCRIPT_DIRNAME / "start-codex.ps1",
        )

    def inspect(self, project_root: Path) -> ProjectTemplateStatus:
        project_root = project_root.resolve()
        backup_root = project_root / ".codex" / "template-backups"
        backup_dir = None
        if backup_root.exists():
            backup_dirs = sorted(
                (path for path in backup_root.iterdir() if path.is_dir()),
                key=lambda path: path.name,
                reverse=True,
            )
            if backup_dirs:
                backup_dir = backup_dirs[0]

        generated_paths = [
            project_root / relative_path
            for relative_path in MANAGED_TEMPLATE_FILES
            if (project_root / relative_path).exists()
        ]
        gitignore_path = project_root / ".gitignore"
        if self._has_managed_gitignore_block(gitignore_path):
            generated_paths.append(gitignore_path)
        return ProjectTemplateStatus(
            generated_paths=generated_paths,
            backup_dir=backup_dir,
            project_root=project_root,
            start_script_path=project_root / CODEX_SCRIPT_DIRNAME / "start-codex.ps1",
        )

    def _backup_managed_files(self, project_root: Path, backup_root: Path) -> Path:
        backup_dir = backup_root / timestamp_label()
        backup_dir.mkdir(parents=True, exist_ok=True)

        for relative_path in BACKUP_TEMPLATE_FILES:
            source = project_root / relative_path
            if not source.exists():
                continue
            destination = backup_dir / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

        return backup_dir

    def _render_files(
        self,
        project_root: Path,
        profile: Profile,
        *,
        global_mcp_toml: str = "",
        project_mcp_toml: str = "",
        agents_doc_text: str | None = None,
        claude_profile: Profile | None = None,
    ) -> dict[str, str]:
        effective_project_mcp_toml = project_mcp_toml or global_mcp_toml
        agents_content = self._render_agents_file(agents_doc_text)
        files = {
            "AGENTS.md": agents_content,
            f"{CODEX_SCRIPT_DIRNAME}/start-codex.ps1": self._render_start_script(),
            f"{CODEX_SCRIPT_DIRNAME}/start-codex.cmd": self._render_cmd_start_script(),
            f"{CODEX_SCRIPT_DIRNAME}/codex-profile.cmd": self._render_profile_launcher(),
            ".gitignore": self._render_gitignore(project_root),
            ".codex/config.toml": dumps_toml(
                render_project_repo_config(
                    profile=profile,
                    project_mcp_toml=effective_project_mcp_toml,
                    project_root=project_root,
                )
            ),
            ".codex/local.env": self._render_local_env(profile.api_key),
            ".codex/local.env.example": self._render_local_env_example(),
            ".codex/home/config.toml": dumps_toml(
                render_project_runtime_config(
                    profile,
                    global_mcp_toml=effective_project_mcp_toml,
                    project_root=project_root,
                )
            ),
            ".codex/home/AGENTS.md": agents_content,
        }
        files.update(
            self._render_claude_files(
                project_root,
                project_mcp_toml=effective_project_mcp_toml,
                agents_doc_text=agents_doc_text,
                profile=claude_profile,
            )
        )
        return files

    def _render_claude_files(
        self,
        project_root: Path,
        *,
        project_mcp_toml: str = "",
        agents_doc_text: str | None = None,
        profile: Profile | None = None,
    ) -> dict[str, str]:
        agents_content = self._render_agents_file(agents_doc_text)
        files = {
            "CLAUDE.md": agents_content,
            ".mcp.json": render_mcp_servers_json(
                scope_mcp_servers_to_project(
                    parse_mcp_servers_toml(project_mcp_toml),
                    project_root,
                )
            ),
        }
        if profile is not None:
            files[".claude/settings.local.json"] = self._render_claude_settings(profile)
        return files

    def _render_claude_settings(self, profile: Profile) -> str:
        payload = self._render_claude_settings_payload(profile)
        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    def _load_claude_settings_payload(self, settings_path: Path) -> dict:
        if not settings_path.exists():
            return {}
        raw = settings_path.read_text(encoding="utf-8").strip()
        if not raw:
            return {}
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("settings.local.json 必须是 JSON 对象。")
        return payload

    def _render_claude_settings_payload(self, profile: Profile, payload: dict | None = None) -> dict:
        rendered = dict(payload or {})
        env = rendered.get("env")
        if not isinstance(env, dict):
            env = {}
        else:
            env = dict(env)
        env.update(
            {
                CLAUDE_BASE_URL_ENV_KEY: profile.base_url.rstrip("/"),
                CLAUDE_API_KEY_ENV_KEY: profile.api_key,
                CLAUDE_MODEL_ENV_KEY: profile.claude_display_model,
                CLAUDE_FALLBACK_MODEL_ENV_KEY: profile.claude_display_fallback_model,
            }
        )
        rendered["env"] = env
        return rendered

    def select_project_mcp_toml(
        self,
        global_mcp_toml: str,
        selected_server_names: list[str] | None,
    ) -> str:
        if selected_server_names is None:
            return global_mcp_toml
        mcp_servers = parse_mcp_servers_toml(global_mcp_toml)
        selected = {
            server_name: mcp_servers[server_name]
            for server_name in selected_server_names
            if server_name in mcp_servers
        }
        return render_mcp_servers_toml(selected)

    def _render_agents_file(self, agents_doc_text: str | None = None) -> str:
        if agents_doc_text is not None:
            return agents_doc_text
        return load_default_agents_doc_text()

    def _render_gitignore(self, project_root: Path) -> str:
        gitignore_path = project_root / ".gitignore"
        existing_text = ""
        if gitignore_path.exists():
            existing_text = gitignore_path.read_text(encoding="utf-8")
        return upsert_managed_gitignore_block(existing_text)

    def _has_managed_gitignore_block(self, gitignore_path: Path) -> bool:
        if not gitignore_path.exists():
            return False
        try:
            content = gitignore_path.read_text(encoding="utf-8")
        except OSError:
            return False
        return GITIGNORE_MANAGED_BEGIN in content and GITIGNORE_MANAGED_END in content

    def _template_asset_path(self, relative_path: str) -> Path:
        return asset_path(relative_path)

    def _render_start_script(self) -> str:
        return """$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
$envFile = Join-Path $projectRoot '.codex\\local.env'
$codexHome = Join-Path $projectRoot '.codex\\home'
$userDataDir = Join-Path $env:LOCALAPPDATA 'Code-codex'
$settingsDir = Join-Path $userDataDir 'User'
$settingsPath = Join-Path $settingsDir 'settings.json'

if (-not (Test-Path -LiteralPath $envFile)) {
  throw "Missing $envFile. Copy .codex\\local.env.example to .codex\\local.env first."
}

if (-not (Test-Path -LiteralPath (Join-Path $codexHome 'config.toml'))) {
  throw "Missing $codexHome\\config.toml."
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
  if ($_ -match '^\\s*([^#=]+?)\\s*=\\s*(.*)\\s*$') {
    [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), 'Process')
  }
}

[Environment]::SetEnvironmentVariable('CODEX_HOME', $codexHome, 'Process')

Start-Process -FilePath $codeCli.Source -ArgumentList @(
  $projectRoot,
  '--new-window',
  '--user-data-dir', $userDataDir
)
"""

    def _render_cmd_start_script(self) -> str:
        return """@echo off
setlocal EnableExtensions

for %%I in ("%~dp0..") do set "PROJECT_ROOT=%%~fI"
set "LAUNCHER=%PROJECT_ROOT%\\codex_scripts\\codex-profile.cmd"

if not exist "%LAUNCHER%" (
  echo Missing "%LAUNCHER%". Generate the project template first. 1^>^&2
  exit /b 1
)

call "%LAUNCHER%" %*
exit /b %errorlevel%
"""

    def _render_local_env(self, api_key: str) -> str:
        return f"{PROJECT_ENV_KEY}={api_key.strip()}\n"

    def _render_local_env_with_key(self, existing_text: str, api_key: str) -> str:
        lines = existing_text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
        rendered: list[str] = []
        updated = False
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in line:
                key, _value = line.split("=", 1)
                if key.strip() == PROJECT_ENV_KEY:
                    rendered.append(self._render_local_env(api_key).rstrip("\n"))
                    updated = True
                    continue
            rendered.append(line)

        if not updated:
            rendered.append(self._render_local_env(api_key).rstrip("\n"))
        return "\n".join(rendered).rstrip("\n") + "\n"

    def _render_local_env_example(self) -> str:
        return (
            "# Copy this file to local.env and fill in your real key.\n"
            "# This file is ignored by git via .gitignore.\n\n"
            f"{PROJECT_ENV_KEY}=sk-your-key-here\n"
        )

    def _render_profile_launcher(self) -> str:
        return """@echo off
setlocal EnableExtensions DisableDelayedExpansion

for %%I in ("%~dp0..") do set "PROJECT_ROOT=%%~fI"
set "ENV_FILE=%PROJECT_ROOT%\\.codex\\local.env"
set "CODEX_HOME=%PROJECT_ROOT%\\.codex\\home"
set "CONFIG_FILE=%CODEX_HOME%\\config.toml"

if not exist "%ENV_FILE%" (
  echo Missing "%ENV_FILE%". Copy .codex\\local.env.example to .codex\\local.env first. 1^>^&2
  exit /b 1
)

if not exist "%CONFIG_FILE%" (
  echo Missing "%CONFIG_FILE%". 1^>^&2
  exit /b 1
)

for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%ENV_FILE%") do (
  if not "%%~A"=="" set "%%~A=%%~B"
)

for /f "delims=" %%I in ('where.exe codex 2^>nul') do (
  if /i not "%%~fI"=="%~f0" (
    set "CODEX_EXE=%%~fI"
    goto run
  )
)

echo Unable to locate the real codex executable from PATH. 1^>^&2
exit /b 1

:run
cd /d "%PROJECT_ROOT%"
call "%CODEX_EXE%" %*
exit /b %errorlevel%
"""
