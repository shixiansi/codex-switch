from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
import json
import shutil
import tomllib

from app_models import CurrentCodexConfig, Profile


DEFAULT_CONFIG: dict = {
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
            lines.append(f"[{'.'.join(path)}]")

        for key, value in scalar_items:
            lines.append(f"{key} = {format_toml_value(value)}")

        if scalar_items and nested_items:
            lines.append("")

        for index, (key, value) in enumerate(nested_items):
            write_table(value, path + [key])
            if index != len(nested_items) - 1:
                lines.append("")

    write_table(data, [])
    return "\n".join(lines).strip() + "\n"


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
            return deepcopy(DEFAULT_CONFIG)
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
        )

    def backup_existing_files(self) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_dir = self.backup_root / timestamp
        backup_dir.mkdir(parents=True, exist_ok=True)

        if self.config_path.exists():
            shutil.copy2(self.config_path, backup_dir / "config.toml")
        if self.auth_path.exists():
            shutil.copy2(self.auth_path, backup_dir / "auth.json")

        return backup_dir

    def apply_profile(self, profile: Profile) -> Path:
        config = self.load_raw_config()
        backup_dir = self.backup_existing_files()

        config["model_provider"] = profile.provider_name
        config["model"] = profile.model
        config["review_model"] = profile.model

        providers = config.setdefault("model_providers", {})
        providers[profile.provider_name] = {
            "name": profile.provider_name,
            "base_url": profile.base_url.rstrip("/"),
            "wire_api": profile.wire_api,
            "requires_openai_auth": profile.requires_openai_auth,
        }

        self.write_config(config)
        self.write_auth(
            {
                "auth_mode": "apikey",
                "OPENAI_API_KEY": profile.api_key,
            }
        )

        return backup_dir

    def write_config(self, config: dict) -> None:
        self.config_path.write_text(dumps_toml(config), encoding="utf-8")

    def write_auth(self, auth: dict) -> None:
        with self.auth_path.open("w", encoding="utf-8") as handle:
            json.dump(auth, handle, ensure_ascii=False, indent=2)
