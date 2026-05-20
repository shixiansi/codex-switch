from __future__ import annotations

from pathlib import Path
import json
import os

from codex_switch.codex_config import load_default_global_mcp_toml
from codex_switch.models import Profile, ProjectRecord
from codex_switch.project_template import load_default_agents_doc_text


MODEL_BATCH_CONCURRENCY_MIN = 1
MODEL_BATCH_CONCURRENCY_MAX = 5
DEFAULT_MODEL_BATCH_CONCURRENCY = 3


def clamp_model_batch_concurrency(value) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = DEFAULT_MODEL_BATCH_CONCURRENCY
    return max(MODEL_BATCH_CONCURRENCY_MIN, min(MODEL_BATCH_CONCURRENCY_MAX, parsed))


class ProfileStore:
    def __init__(self, root_dir: Path | None = None) -> None:
        if root_dir is None:
            appdata = os.environ.get("APPDATA")
            if appdata:
                root_dir = Path(appdata) / "CodexSwitch"
            else:
                root_dir = Path.home() / ".codex-switch"
        self.root_dir = root_dir
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.storage_path = self.root_dir / "profiles.json"

    def load(self) -> tuple[list[Profile], str | None, list[ProjectRecord], str | None, bool, str, list[str], bool, str, int, dict]:
        default_global_mcp_toml = load_default_global_mcp_toml()
        default_agents_doc_text = load_default_agents_doc_text()
        if not self.storage_path.exists():
            return [], None, [], None, False, default_global_mcp_toml, [], False, default_agents_doc_text, DEFAULT_MODEL_BATCH_CONCURRENCY, {}

        try:
            with self.storage_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (json.JSONDecodeError, OSError):
            return [], None, [], None, False, default_global_mcp_toml, [], False, default_agents_doc_text, DEFAULT_MODEL_BATCH_CONCURRENCY, {}

        profiles = [Profile.from_dict(item) for item in payload.get("profiles", [])]
        selected_profile_id = payload.get("selected_profile_id")
        projects = [ProjectRecord.from_dict(item) for item in payload.get("projects", [])]
        selected_project_id = payload.get("selected_project_id")
        ui_payload = payload.get("ui", {})
        hide_error_profiles = False
        if isinstance(ui_payload, dict):
            hide_error_profiles = bool(ui_payload.get("hide_error_profiles", False))
        elif "hide_error_profiles" in payload:
            hide_error_profiles = bool(payload.get("hide_error_profiles"))
        settings_payload = payload.get("settings", {})
        global_mcp_toml = default_global_mcp_toml
        applied_global_mcp_server_names: list[str] = []
        global_mcp_opt_out = False
        agents_doc_text = default_agents_doc_text
        model_batch_concurrency = DEFAULT_MODEL_BATCH_CONCURRENCY
        model_batch_cache_by_profile: dict = {}
        if isinstance(settings_payload, dict):
            global_mcp_opt_out = bool(settings_payload.get("global_mcp_opt_out", False))
            if "global_mcp_toml" in settings_payload:
                stored_global_mcp_toml = str(settings_payload.get("global_mcp_toml", "") or "")
                if stored_global_mcp_toml.strip():
                    global_mcp_toml = stored_global_mcp_toml
                elif global_mcp_opt_out:
                    global_mcp_toml = ""
            applied_names = settings_payload.get("applied_global_mcp_server_names", [])
            if isinstance(applied_names, list):
                applied_global_mcp_server_names = [str(item) for item in applied_names if str(item).strip()]
            if "agents_doc_text" in settings_payload:
                agents_doc_text = str(settings_payload.get("agents_doc_text") or "")
            model_batch_concurrency = clamp_model_batch_concurrency(
                settings_payload.get("model_batch_concurrency", DEFAULT_MODEL_BATCH_CONCURRENCY)
            )
            stored_model_batch_cache = settings_payload.get("model_batch_cache_by_profile", {})
            if isinstance(stored_model_batch_cache, dict):
                model_batch_cache_by_profile = stored_model_batch_cache
        return (
            profiles,
            selected_profile_id,
            projects,
            selected_project_id,
            hide_error_profiles,
            global_mcp_toml,
            applied_global_mcp_server_names,
            global_mcp_opt_out,
            agents_doc_text,
            model_batch_concurrency,
            model_batch_cache_by_profile,
        )

    def save(
        self,
        profiles: list[Profile],
        selected_profile_id: str | None,
        projects: list[ProjectRecord] | None = None,
        selected_project_id: str | None = None,
        hide_error_profiles: bool = False,
        global_mcp_toml: str = "",
        applied_global_mcp_server_names: list[str] | None = None,
        global_mcp_opt_out: bool = False,
        agents_doc_text: str | None = None,
        model_batch_concurrency: int = DEFAULT_MODEL_BATCH_CONCURRENCY,
        model_batch_cache_by_profile: dict | None = None,
    ) -> None:
        if agents_doc_text is None:
            agents_doc_text = load_default_agents_doc_text()
        payload = {
            "version": 5,
            "selected_profile_id": selected_profile_id,
            "profiles": [profile.to_dict() for profile in profiles],
            "selected_project_id": selected_project_id,
            "projects": [project.to_dict() for project in (projects or [])],
            "ui": {
                "hide_error_profiles": hide_error_profiles,
            },
            "settings": {
                "global_mcp_toml": global_mcp_toml,
                "applied_global_mcp_server_names": list(applied_global_mcp_server_names or []),
                "global_mcp_opt_out": global_mcp_opt_out,
                "agents_doc_text": agents_doc_text,
                "model_batch_concurrency": clamp_model_batch_concurrency(model_batch_concurrency),
                "model_batch_cache_by_profile": dict(model_batch_cache_by_profile or {}),
            },
        }
        with self.storage_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
