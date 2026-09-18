import QtQuick
import QtQuick.Controls
import theme

// Primary push button: solid accent, hover/press feedback, optional icon.
Button {
    id: control

    property string iconName: ""
    // Optional trailing glyph meaning "this opens something" (a menu / a
    // dialog). Empty by default, so every existing button is unchanged.
    property string trailingIconName: ""
    property string variant: "secondary"   // primary | secondary | danger | ghost
    property int iconSize: 16
    // Compact square-ish button for single-glyph content (↑ ↓ ← →): a
    // full-width button around one arrow looks like an empty box.
    property bool compact: false

    implicitHeight: Theme.controlHeight
    implicitWidth: compact
        ? Theme.controlHeight
        : Math.max(Theme.controlHeight * 2, contentRow.implicitWidth + Theme.space3 * 2)
    padding: 0

    readonly property bool isPrimary: variant === "primary"
    readonly property bool isDanger: variant === "danger"
    readonly property bool isGhost: variant === "ghost"

    // Disabled state must be *visible*.
    //
    // Previously neither the label colour nor the fill consulted `enabled`, so
    // a disabled button was pixel-identical to an enabled one: "发送" with an
    // empty box, and "载入项目历史" without a session, both looked clickable.
    // Opacity is the reliable lever — it dims fill, border and text at once
    // without having to restate every colour per state.
    readonly property real _disabledOpacity: 0.45

    readonly property color _fg: {
        if (isPrimary)
            return Theme.accentText
        if (isDanger)
            return "#FFFFFF"
        return control.hovered || control.down ? Theme.text : Theme.textMuted
    }

    readonly property color _borderColor: isPrimary || isDanger ? "transparent" : Theme.border

    // The painted colour and its opacity are separated so the ghost variant can
    // fade in instead of animating `color` from "transparent". "transparent" is
    // rgba(0,0,0,0), so a colour animation interpolates from BLACK and the
    // button briefly darkens — a visible flash on hover.
    readonly property color _bgSolid: {
        if (isPrimary)
            return control.down ? Qt.darker(Theme.accent, 1.15) : (control.hovered ? Theme.accentHover : Theme.accent)
        if (isDanger)
            return control.down ? Qt.darker(Theme.danger, 1.15) : (control.hovered ? Qt.lighter(Theme.danger, 1.06) : Theme.danger)
        if (isGhost)
            // Faded in/out via opacity, so a hover tone is always painted.
            return control.down ? Theme.surfaceActive : Theme.surfaceHover
        // Secondary: an opaque card surface at rest.
        return control.down ? Theme.surfaceActive : (control.hovered ? Theme.surfaceHover : Theme.surface)
    }

    readonly property real _bgOpacity: (isGhost && !control.hovered && !control.down) ? 0 : 1

    // The two independent opacity needs are kept separate: `opacity` dims the
    // whole control (used for the disabled state), while the background keeps
    // its own `_bgOpacity` so the ghost fade animation stays untouched.
    opacity: control.enabled ? 1.0 : _disabledOpacity

    background: Rectangle {
        radius: Theme.radiusSm
        color: control._bgSolid
        opacity: control._bgOpacity
        border.width: control.isGhost ? 0 : Theme.borderWidth
        border.color: control._borderColor

        // Ghost fades its tinted layer; the others animate between two opaque
        // tones, which never passes through black.
        Behavior on opacity {
            enabled: control.isGhost
            NumberAnimation {
                duration: Theme.durationFast
                easing.type: Easing.OutCubic
            }
        }

        Behavior on color {
            enabled: !control.isGhost
            ColorAnimation { duration: Theme.durationFast }
        }
    }

    contentItem: Item {
        // Qt Quick Controls stretches contentItem to fill the button, so a Row
        // with anchors.centerIn would be overridden and the label would sit
        // flush left. Centering the Row inside a wrapper keeps short labels
        // ("编辑") visually centred instead of left-aligned.
        implicitWidth: contentRow.implicitWidth
        implicitHeight: contentRow.implicitHeight

        Row {
            id: contentRow
            spacing: control.iconName !== "" ? Theme.space1 + 2 : 0
            anchors.centerIn: parent

            AppIcon {
                name: control.iconName
                color: control._fg
                size: control.iconSize
                visible: control.iconName !== ""
                anchors.verticalCenter: parent.verticalCenter
            }

            Text {
                text: control.text
                color: control._fg
                font.pixelSize: Theme.fontBody
                font.weight: control.isPrimary ? Font.DemiBold : Font.Normal
                anchors.verticalCenter: parent.verticalCenter
                elide: Text.ElideRight
            }

            // Trailing chevron: signals "opens a menu / dialog". A QML Row skips
            // items with visible:false entirely (verified), so an empty name
            // leaves the layout byte-for-byte as before.
            AppIcon {
                name: control.trailingIconName
                color: control._fg
                size: control.iconSize - 2
                opacity: 0.7
                visible: control.trailingIconName !== ""
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }

    ToolTip.visible: hovered && ToolTip.text !== ""
    ToolTip.delay: 500
    ToolTip.text: ""
}
