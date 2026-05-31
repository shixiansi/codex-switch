from __future__ import annotations

from pathlib import Path
import json
import shutil

from codex_switch.codex_config import timestamp_label
from codex_switch.models import Profile
from codex_switch.project_template import load_claude_settings_payload, render_claude_settings_payload


class ClaudeConfigManager:
    def __init__(
        self,
        claude_dir: Path | None = None,
        backup_root: Path | None = None,
    ) -> None:
        self.claude_dir = claude_dir or (Path.home() / ".claude")
        self.settings_path = self.claude_dir / "settings.json"
        self.claude_dir.mkdir(parents=True, exist_ok=True)
        self.backup_root = backup_root or (self.claude_dir / "switch-backups")
        self.backup_root.mkdir(parents=True, exist_ok=True)

    def load_settings(self) -> dict:
        return load_claude_settings_payload(self.settings_path)

    def backup_existing_files(self) -> Path:
        backup_dir = self.backup_root / timestamp_label()
        backup_dir.mkdir(parents=True, exist_ok=True)
        if self.settings_path.exists():
            shutil.copy2(self.settings_path, backup_dir / "settings.json")
        return backup_dir

    def apply_profile(self, profile: Profile) -> Path:
        payload = render_claude_settings_payload(profile, self.load_settings())
        backup_dir = self.backup_existing_files()
        self.write_settings(payload)
        return backup_dir

    def write_settings(self, payload: dict) -> None:
        self.settings_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
