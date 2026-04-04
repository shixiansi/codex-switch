from __future__ import annotations

from pathlib import Path
import json
import os

from app_models import Profile


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

    def load(self) -> tuple[list[Profile], str | None]:
        if not self.storage_path.exists():
            return [], None

        with self.storage_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)

        profiles = [Profile.from_dict(item) for item in payload.get("profiles", [])]
        selected_profile_id = payload.get("selected_profile_id")
        return profiles, selected_profile_id

    def save(self, profiles: list[Profile], selected_profile_id: str | None) -> None:
        payload = {
            "version": 1,
            "selected_profile_id": selected_profile_id,
            "profiles": [profile.to_dict() for profile in profiles],
        }
        with self.storage_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
