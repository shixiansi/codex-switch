from __future__ import annotations

from pathlib import Path
import json
import os

from codex_switch.codex_config import load_default_global_mcp_toml
from codex_switch.models import Profile, ProjectRecord
from codex_switch.project_template import load_default_agents_doc_text


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

    def load(self) -> tuple[list[Profile], str | None, list[ProjectRecord], str | None, bool, str, list[str], bool, str]:
        default_global_mcp_toml = load_default_global_mcp_toml()
        default_agents_doc_text = load_default_agents_doc_text()
        if not self.storage_path.exists():
            return [], None, [], None, False, default_global_mcp_toml, [], False, default_agents_doc_text

        try:
            with self.storage_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (json.JSONDecodeError, OSError):
            return [], None, [], None, False, default_global_mcp_toml, [], False, default_agents_doc_text

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
    ) -> None:
        if agents_doc_text is None:
            agents_doc_text = load_default_agents_doc_text()
        payload = {
            "version": 4,
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
            },
        }
        with self.storage_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
