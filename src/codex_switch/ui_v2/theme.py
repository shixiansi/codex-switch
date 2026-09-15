"""Design tokens for the QML UI.

Colours live here only; components read them through the ``Theme`` singleton,
so switching light/dark never requires touching a component.
"""

from __future__ import annotations

from typing import Any

from .qt_compat import Property, QObject, Signal, Slot


# 8px spacing system, restrained radii, low-elevation surfaces.
METRICS: dict[str, int] = {
    "unit": 8,
    "space1": 4,
    "space2": 8,
    "space3": 12,
    "space4": 16,
    "space5": 24,
    "space6": 32,
    "radius": 12,
    "radiusSm": 8,
    "radiusLg": 14,
    "controlHeight": 34,
    "controlHeightSm": 28,
    "navWidth": 224,
    "drawerWidth": 440,
    "topBarHeight": 56,
    "statusBarHeight": 30,
    "rowHeight": 40,
    "borderWidth": 1,
}

TYPOGRAPHY: dict[str, int] = {
    "display": 22,
    "title": 16,
    "subtitle": 14,
    "body": 13,
    "caption": 12,
    "mono": 12,
}

# Blue-violet accent, fixed semantic status colours.
LIGHT_COLORS: dict[str, str] = {
    "bg": "#F4F6FB",
    "surface": "#FFFFFF",
    "surfaceAlt": "#EEF1F8",
    "surfaceHover": "#E7ECF6",
    "surfaceActive": "#DFE6F4",
    "border": "#E2E8F0",
    "borderStrong": "#CBD5E1",
    "text": "#0F172A",
    "textMuted": "#64748B",
    "textFaint": "#94A3B8",
    "accent": "#5B5CE2",
    "accentHover": "#4C4DD6",
    "accentSoft": "#EEF0FF",
    "accentText": "#FFFFFF",
    "success": "#159947",
    "successSoft": "#E6F6EC",
    "warning": "#C47A12",
    "warningSoft": "#FDF3E2",
    "danger": "#D64545",
    "dangerSoft": "#FCECEC",
    "info": "#2A72D4",
    "infoSoft": "#E8F1FC",
    "unknown": "#94A3B8",
    "unknownSoft": "#EEF1F6",
    "shadow": "#1A0F172A",
    "overlay": "#66101828",
    "codeBg": "#F7F9FC",
}

DARK_COLORS: dict[str, str] = {
    "bg": "#0B0F17",
    "surface": "#141A24",
    "surfaceAlt": "#1B2330",
    "surfaceHover": "#222C3B",
    "surfaceActive": "#2A3648",
    "border": "#2A3545",
    "borderStrong": "#3A4759",
    "text": "#E8EEF7",
    "textMuted": "#93A0B4",
    "textFaint": "#6B778C",
    "accent": "#8B8DFF",
    "accentHover": "#9EA0FF",
    "accentSoft": "#24264A",
    "accentText": "#0B0F17",
    "success": "#3DDB8A",
    "successSoft": "#14301F",
    "warning": "#F0B429",
    "warningSoft": "#33260D",
    "danger": "#F07178",
    "dangerSoft": "#3A1B1F",
    "info": "#6BB0F5",
    "infoSoft": "#152A42",
    "unknown": "#6B778C",
    "unknownSoft": "#1E2634",
    "shadow": "#00000000",
    "overlay": "#99000000",
    "codeBg": "#0F1520",
}

# Health/status tone -> colour token name, shared by cards, badges and rows.
STATUS_TONES: dict[str, str] = {
    "healthy": "success",
    "success": "success",
    "degraded": "warning",
    "restricted": "warning",
    "warning": "warning",
    "error": "danger",
    "danger": "danger",
    "failed": "danger",
    "unknown": "unknown",
    "info": "info",
    "accent": "accent",
}


class ThemeController(QObject):
    """Exposes the active token set to QML and persists theme preference."""

    darkModeChanged = Signal()
    tokensChanged = Signal()

    def __init__(self, dark_mode: bool = False, on_change=None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._dark_mode = bool(dark_mode)
        self._on_change = on_change

    @Property(bool, notify=darkModeChanged)
    def darkMode(self) -> bool:
        return self._dark_mode

    @darkMode.setter
    def darkMode(self, value: bool) -> None:
        self.setDarkMode(bool(value))

    @Property("QVariantMap", notify=tokensChanged)
    def colors(self) -> dict[str, Any]:
        return dict(DARK_COLORS if self._dark_mode else LIGHT_COLORS)

    @Property("QVariantMap", constant=True)
    def metrics(self) -> dict[str, Any]:
        return dict(METRICS)

    @Property("QVariantMap", constant=True)
    def typography(self) -> dict[str, Any]:
        return dict(TYPOGRAPHY)

    @Property("QVariantMap", constant=True)
    def tones(self) -> dict[str, Any]:
        return dict(STATUS_TONES)

    @Property(str, notify=darkModeChanged)
    def label(self) -> str:
        return "深色" if self._dark_mode else "浅色"

    @Slot(bool)
    def setDarkMode(self, value: bool) -> None:
        value = bool(value)
        if value == self._dark_mode:
            return
        self._dark_mode = value
        self.darkModeChanged.emit()
        self.tokensChanged.emit()
        if self._on_change is not None:
            self._on_change(value)

    @Slot()
    def toggle(self) -> None:
        self.setDarkMode(not self._dark_mode)

    def tone_color(self, tone: str) -> str:
        """Resolve a status tone to a hex colour (used by snapshot payloads)."""
        palette = DARK_COLORS if self._dark_mode else LIGHT_COLORS
        return palette.get(STATUS_TONES.get(str(tone or "unknown"), "unknown"), palette["unknown"])


__all__ = [
    "DARK_COLORS",
    "LIGHT_COLORS",
    "METRICS",
    "STATUS_TONES",
    "TYPOGRAPHY",
    "ThemeController",
]
