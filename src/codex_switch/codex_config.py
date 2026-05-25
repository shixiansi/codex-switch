from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
import json
import re
import shutil
import sys
import tomllib

from codex_switch.models import CurrentCodexConfig, Profile
from codex_switch.resources import asset_path_candidates


GLOBAL_BASE_CONFIG: dict = {
    "model_provider": "OpenAI",
    "model": "gpt-5.4",
    "review_model": "gpt-5.4",
    "model_reasoning_effort": "xhigh",
    "disable_response_storage": True,
    "network_access": "enabled",
    "windows_wsl_setup_acknowledged": True,
    "model_context_window": 1000000,
    "model_auto_compact_token_limit": 900000,
    "model_providers": {
        "OpenAI": {
            "name": "OpenAI",
            "base_url": "https://api.openai.com",
            "wire_api": "responses",
            "requires_openai_auth": True,
        }
    },
    "windows": {
        "sandbox": "elevated",
    },
}

PROJECT_BASE_CONFIG: dict = {
    "model": "gpt-5.4",
    "review_model": "gpt-5.4",
    "model_reasoning_effort": "xhigh",
    "disable_response_storage": True,
    "network_access": "enabled",
    "model_context_window": 1000000,
    "model_auto_compact_token_limit": 900000,
    "windows": {
        "sandbox": "elevated",
    },
}

PROJECT_PROVIDER_ID = "project_api"
PROJECT_ENV_KEY = "PROJECT_API_KEY"
DEFAULT_GLOBAL_MCP_ASSET = "mcp-servers-2026-04-11.json"
PROJECT_ROOT_PLACEHOLDER = "{project_root}"
TOML_BARE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def timestamp_label() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def format_toml_key(key: str) -> str:
    return key if TOML_BARE_KEY_RE.match(key) else json.dumps(key, ensure_ascii=False)


def format_toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(format_toml_value(item) for item in value) + "]"
    raise TypeError(f"Unsupported TOML value: {type(value)!r}")


def dumps_toml(data: dict) -> str:
    lines: list[str] = []

    def write_table(table: dict, path: list[str]) -> None:
        scalar_items: list[tuple[str, object]] = []
        nested_items: list[tuple[str, dict]] = []

        for key, value in table.items():
            if value is None:
                continue
            if isinstance(value, dict):
                nested_items.append((key, value))
            else:
                scalar_items.append((key, value))

        if path:
            lines.append(f"[{'.'.join(format_toml_key(part) for part in path)}]")

        for key, value in scalar_items:
            lines.append(f"{format_toml_key(key)} = {format_toml_value(value)}")

        if scalar_items and nested_items:
            lines.append("")

        for index, (key, value) in enumerate(nested_items):
            write_table(value, path + [key])
            if index != len(nested_items) - 1:
                lines.append("")

    write_table(data, [])
    return "\n".join(lines).strip() + "\n"


def _asset_path_candidates(relative_path: str) -> list[Path]:
    return asset_path_candidates(relative_path)


def render_mcp_servers_toml(mcp_servers: dict[str, dict] | None) -> str:
    normalized: dict[str, dict] = {}
    for server_name, server_config in (mcp_servers or {}).items():
        if isinstance(server_config, dict):
            normalized[str(server_name)] = deepcopy(server_config)
    if not normalized:
        return ""
    return dumps_toml({"mcp_servers": normalized})


def parse_mcp_servers_json(raw_json: str | None) -> dict[str, dict]:
    if not raw_json or not raw_json.strip():
        return {}

    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"MCP JSON 无法解析：{exc}") from exc

    unexpected_keys = [key for key in payload.keys() if key != "mcpServers"]
    if unexpected_keys:
        raise ValueError("MCP JSON 只支持顶层 mcpServers 配置。")

    mcp_servers = payload.get("mcpServers", {})
    if not isinstance(mcp_servers, dict):
        raise ValueError("mcpServers 必须是一个 JSON object。")

    normalized: dict[str, dict] = {}
    for server_name, server_config in mcp_servers.items():
        if not isinstance(server_config, dict):
            raise ValueError(f"mcpServers.{server_name} 必须是一个 JSON object。")
        normalized[str(server_name)] = deepcopy(server_config)
    return normalized


def load_default_global_mcp_toml(asset_name: str = DEFAULT_GLOBAL_MCP_ASSET) -> str:
    for candidate in _asset_path_candidates(asset_name):
        if not candidate.exists():
            continue
        try:
            raw_json = candidate.read_text(encoding="utf-8")
            return render_mcp_servers_toml(parse_mcp_servers_json(raw_json))
        except (OSError, ValueError):
            continue
    return ""


def _scope_filesystem_server_to_project(server_config: dict, project_dir: str) -> None:
    args = server_config.get("args")
    if not isinstance(args, list):
        return

    scoped_args = [str(item) for item in args]
    if scoped_args:
        scoped_args[-1] = project_dir
    else:
        scoped_args.append(project_dir)
    server_config["args"] = scoped_args


def _scope_serena_server_to_project(server_config: dict, project_dir: str) -> None:
    args = server_config.get("args")
    if not isinstance(args, list):
        return

    scoped_args = [str(item) for item in args]
    try:
        project_index = scoped_args.index("--project")
    except ValueError:
        scoped_args.extend(["--project", project_dir])
    else:
        if project_index == len(scoped_args) - 1:
            scoped_args.append(project_dir)
        else:
            scoped_args[project_index + 1] = project_dir
    server_config["args"] = scoped_args


def _contains_project_root_placeholder(value) -> bool:
    if isinstance(value, str):
        return PROJECT_ROOT_PLACEHOLDER in value
    if isinstance(value, list):
        return any(_contains_project_root_placeholder(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_project_root_placeholder(item) for item in value.values())
    return False


def _replace_project_root_placeholders(value, project_dir: str):
    if isinstance(value, str):
        return value.replace(PROJECT_ROOT_PLACEHOLDER, project_dir)
    if isinstance(value, list):
        return [_replace_project_root_placeholders(item, project_dir) for item in value]
    if isinstance(value, dict):
        return {
            key: _replace_project_root_placeholders(item, project_dir)
            for key, item in value.items()
        }
    return value


def scope_mcp_servers_to_project(
    mcp_servers: dict[str, dict] | None,
    project_root: str | Path | None,
) -> dict[str, dict]:
    scoped = deepcopy(mcp_servers or {})
    if project_root is None:
        return scoped

    project_dir = str(Path(project_root).resolve())
    servers_using_placeholder = {
        server_name
        for server_name, server_config in scoped.items()
        if _contains_project_root_placeholder(server_config)
    }
    scoped = _replace_project_root_placeholders(scoped, project_dir)

    filesystem_server = scoped.get("filesystem")
    if isinstance(filesystem_server, dict) and "filesystem" not in servers_using_placeholder:
        _scope_filesystem_server_to_project(filesystem_server, project_dir)

    serena_server = scoped.get("serena")
    if isinstance(serena_server, dict) and "serena" not in servers_using_placeholder:
        _scope_serena_server_to_project(serena_server, project_dir)

    return scoped


def build_provider_payload(
    profile: Profile,
    *,
    env_key: str | None = None,
    include_requires_openai_auth: bool = True,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": profile.provider_name,
        "base_url": profile.base_url.rstrip("/"),
        "wire_api": profile.wire_api,
    }
    if env_key:
        payload["env_key"] = env_key
    elif include_requires_openai_auth:
        payload["requires_openai_auth"] = profile.requires_openai_auth
    return payload


def parse_mcp_servers_toml(raw_toml: str | None) -> dict[str, dict]:
    if not raw_toml or not raw_toml.strip():
        return {}

    try:
        payload = tomllib.loads(raw_toml)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"MCP TOML 无法解析：{exc}") from exc

    unexpected_keys = [key for key in payload.keys() if key != "mcp_servers"]
    if unexpected_keys:
        raise ValueError("MCP TOML 只支持 [mcp_servers.<name>] 相关配置。")

    mcp_servers = payload.get("mcp_servers", {})
    if not isinstance(mcp_servers, dict):
        raise ValueError("mcp_servers 必须是一个 TOML table。")

    normalized: dict[str, dict] = {}
    for server_name, server_config in mcp_servers.items():
        if not isinstance(server_config, dict):
            raise ValueError(f"mcp_servers.{server_name} 必须是一个 TOML table。")
        normalized[str(server_name)] = deepcopy(server_config)
    return normalized


def mcp_server_names_from_toml(raw_toml: str | None) -> list[str]:
    return sorted(parse_mcp_servers_toml(raw_toml).keys())


def merge_mcp_servers(
    config: dict,
    *,
    managed_mcp_servers: dict[str, dict] | None = None,
    remove_server_names: list[str] | None = None,
) -> dict:
    servers = deepcopy(config.get("mcp_servers", {})) if isinstance(config.get("mcp_servers"), dict) else {}

    for server_name in remove_server_names or []:
        servers.pop(server_name, None)

    for server_name, server_config in (managed_mcp_servers or {}).items():
        servers[server_name] = deepcopy(server_config)

    if servers:
        config["mcp_servers"] = servers
    else:
        config.pop("mcp_servers", None)
    return config


def render_global_config(
    profile: Profile,
    existing_config: dict | None = None,
    *,
    global_mcp_toml: str = "",
    previous_managed_mcp_server_names: list[str] | None = None,
) -> dict:
    config = deepcopy(existing_config) if existing_config is not None else deepcopy(GLOBAL_BASE_CONFIG)
    config["model_provider"] = profile.provider_name
    config["model"] = profile.model
    config["review_model"] = profile.model
    providers = config.setdefault("model_providers", {})
    providers[profile.provider_name] = build_provider_payload(profile)
    merge_mcp_servers(
        config,
        managed_mcp_servers=parse_mcp_servers_toml(global_mcp_toml),
        remove_server_names=previous_managed_mcp_server_names,
    )
    return config


def render_global_auth(profile: Profile) -> dict[str, str]:
    return {
        "auth_mode": "apikey",
        "OPENAI_API_KEY": profile.api_key,
    }


def render_project_base_config(*, project_mcp_toml: str = "", model: str | None = None) -> dict:
    config = deepcopy(PROJECT_BASE_CONFIG)
    if model:
        config["model"] = model
        config["review_model"] = model
    return config


def render_project_runtime_config(
    profile: Profile,
    *,
    global_mcp_toml: str = "",
    project_root: str | Path | None = None,
) -> dict:
    config = render_project_base_config()
    config["model_provider"] = PROJECT_PROVIDER_ID
    config["model"] = profile.model
    config["review_model"] = profile.model
    config["model_providers"] = {
        PROJECT_PROVIDER_ID: build_provider_payload(
            profile,
            env_key=PROJECT_ENV_KEY,
            include_requires_openai_auth=False,
        )
    }
    merge_mcp_servers(
        config,
        managed_mcp_servers=scope_mcp_servers_to_project(
            parse_mcp_servers_toml(global_mcp_toml),
            project_root,
        ),
    )
    return config


def render_project_repo_config(
    *,
    profile: Profile | None = None,
    project_mcp_toml: str = "",
    project_root: str | Path | None = None,
) -> dict:
    config = render_project_base_config(
        project_mcp_toml=project_mcp_toml,
        model=profile.model if profile else None,
    )
    merge_mcp_servers(
        config,
        managed_mcp_servers=scope_mcp_servers_to_project(
            parse_mcp_servers_toml(project_mcp_toml),
            project_root,
        ),
    )
    return config


class CodexConfigManager:
    def __init__(
        self,
        codex_dir: Path | None = None,
        backup_root: Path | None = None,
    ) -> None:
        self.codex_dir = codex_dir or (Path.home() / ".codex")
        self.config_path = self.codex_dir / "config.toml"
        self.auth_path = self.codex_dir / "auth.json"
        self.codex_dir.mkdir(parents=True, exist_ok=True)
        self.backup_root = backup_root or (self.codex_dir / "switch-backups")
        self.backup_root.mkdir(parents=True, exist_ok=True)

    def load_raw_config(self) -> dict:
        if not self.config_path.exists():
            return deepcopy(GLOBAL_BASE_CONFIG)
        with self.config_path.open("rb") as handle:
            return tomllib.load(handle)

    def load_auth(self) -> dict:
        if not self.auth_path.exists():
            return {}
        with self.auth_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def read_current_config(self) -> CurrentCodexConfig:
        config = self.load_raw_config()
        auth = self.load_auth()

        model_provider = config.get("model_provider")
        provider_config = config.get("model_providers", {}).get(model_provider, {})
        mcp_servers = config.get("mcp_servers", {})
        if not isinstance(mcp_servers, dict):
            mcp_servers = {}

        return CurrentCodexConfig(
            model_provider=model_provider,
            model=config.get("model"),
            review_model=config.get("review_model"),
            base_url=provider_config.get("base_url"),
            wire_api=provider_config.get("wire_api"),
            requires_openai_auth=provider_config.get("requires_openai_auth"),
            auth_mode=auth.get("auth_mode"),
            api_key=auth.get("OPENAI_API_KEY"),
            config_path=str(self.config_path),
            auth_path=str(self.auth_path),
            mcp_server_names=sorted(key for key, value in mcp_servers.items() if isinstance(value, dict)),
        )

    def backup_existing_files(self) -> Path:
        backup_dir = self.backup_root / timestamp_label()
        backup_dir.mkdir(parents=True, exist_ok=True)

        if self.config_path.exists():
            shutil.copy2(self.config_path, backup_dir / "config.toml")
        if self.auth_path.exists():
            shutil.copy2(self.auth_path, backup_dir / "auth.json")

        return backup_dir

    def apply_profile(
        self,
        profile: Profile,
        *,
        global_mcp_toml: str = "",
        previous_managed_mcp_server_names: list[str] | None = None,
    ) -> Path:
        config = render_global_config(
            profile,
            existing_config=self.load_raw_config(),
            global_mcp_toml=global_mcp_toml,
            previous_managed_mcp_server_names=previous_managed_mcp_server_names,
        )
        backup_dir = self.backup_existing_files()

        self.write_config(config)
        self.write_auth(render_global_auth(profile))

        return backup_dir

    def write_config(self, config: dict) -> None:
        self.config_path.write_text(dumps_toml(config), encoding="utf-8")

    def write_auth(self, auth: dict) -> None:
        with self.auth_path.open("w", encoding="utf-8") as handle:
            json.dump(auth, handle, ensure_ascii=False, indent=2)
