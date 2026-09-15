pragma Singleton
import QtQuick

// Maps semantic icon names to bundled local SVGs.
// Icons are recoloured at draw time through MultiEffect, so a single black
// stroke SVG serves every theme and state.
QtObject {
    // Icons live in ui_v2/assets/icons (outside the qml tree), so resolve from
    // this file's directory: qml/theme/ -> ../../assets/icons/。
    readonly property url base: Qt.resolvedUrl("../../assets/icons/")

    function source(name) {
        var key = String(name || "").trim()
        if (key === "")
            return ""
        return base + key + ".svg"
    }
}
