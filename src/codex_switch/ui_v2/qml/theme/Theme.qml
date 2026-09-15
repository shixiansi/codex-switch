pragma Singleton
import QtQuick

// Design tokens for the whole UI.
//
// Colours come from Python (codex_switch.ui_v2.theme) so there is exactly one
// source of truth for the palette and the light/dark switch. Metrics and
// typography are fixed here because they do not change with the theme.
QtObject {
    id: theme

    // -- colours (single source of truth: Python ThemeController) --------
    readonly property color bg: app.themeController.colors.bg
    readonly property color surface: app.themeController.colors.surface
    readonly property color surfaceAlt: app.themeController.colors.surfaceAlt
    readonly property color surfaceHover: app.themeController.colors.surfaceHover
    readonly property color surfaceActive: app.themeController.colors.surfaceActive
    readonly property color border: app.themeController.colors.border
    readonly property color borderStrong: app.themeController.colors.borderStrong
    readonly property color text: app.themeController.colors.text
    readonly property color textMuted: app.themeController.colors.textMuted
    readonly property color textFaint: app.themeController.colors.textFaint
    readonly property color accent: app.themeController.colors.accent
    readonly property color accentHover: app.themeController.colors.accentHover
    readonly property color accentSoft: app.themeController.colors.accentSoft
    readonly property color accentText: app.themeController.colors.accentText
    readonly property color success: app.themeController.colors.success
    readonly property color successSoft: app.themeController.colors.successSoft
    readonly property color warning: app.themeController.colors.warning
    readonly property color warningSoft: app.themeController.colors.warningSoft
    readonly property color danger: app.themeController.colors.danger
    readonly property color dangerSoft: app.themeController.colors.dangerSoft
    readonly property color info: app.themeController.colors.info
    readonly property color infoSoft: app.themeController.colors.infoSoft
    readonly property color unknown: app.themeController.colors.unknown
    readonly property color unknownSoft: app.themeController.colors.unknownSoft
    readonly property color overlay: app.themeController.colors.overlay
    readonly property color codeBg: app.themeController.colors.codeBg

    readonly property bool dark: app.themeController.darkMode

    // -- metrics (8px system) --------------------------------------------
    readonly property int unit: 8
    readonly property int space1: 4
    readonly property int space2: 8
    readonly property int space3: 12
    readonly property int space4: 16
    readonly property int space5: 24
    readonly property int space6: 32
    readonly property int radius: 12
    readonly property int radiusSm: 8
    readonly property int radiusLg: 14
    readonly property int controlHeight: 34
    readonly property int controlHeightSm: 28
    readonly property int navWidth: 224
    readonly property int drawerWidth: 440
    readonly property int topBarHeight: 56
    readonly property int statusBarHeight: 30
    readonly property int rowHeight: 40
    readonly property int borderWidth: 1

    // -- typography ------------------------------------------------------
    readonly property int fontDisplay: 22
    readonly property int fontTitle: 16
    readonly property int fontSubtitle: 14
    readonly property int fontBody: 13
    readonly property int fontCaption: 12
    readonly property int fontMono: 12

    // -- motion (restrained) ---------------------------------------------
    readonly property int durationFast: 120
    readonly property int durationBase: 180
    readonly property int durationSlow: 260

    // -- helpers ---------------------------------------------------------
    function toneColor(tone) {
        switch (String(tone || "")) {
        case "success": return success
        case "warning": return warning
        case "danger": return danger
        case "info": return info
        case "accent": return accent
        case "unknown": return unknown
        default: return textMuted
        }
    }

    function toneSoftColor(tone) {
        switch (String(tone || "")) {
        case "success": return successSoft
        case "warning": return warningSoft
        case "danger": return dangerSoft
        case "info": return infoSoft
        case "accent": return accentSoft
        default: return unknownSoft
        }
    }

    function healthLabel(status) {
        switch (String(status || "")) {
        case "healthy": return "健康"
        case "degraded":
        case "restricted": return "受限"
        case "error": return "异常"
        default: return "未检测"
        }
    }

    function px(value) {
        return Math.round(value)
    }
}
