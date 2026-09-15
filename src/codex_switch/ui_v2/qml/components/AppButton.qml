import QtQuick
import QtQuick.Controls
import theme

// Primary push button: solid accent, hover/press feedback, optional icon.
Button {
    id: control

    property string iconName: ""
    property string variant: "secondary"   // primary | secondary | danger | ghost
    property int iconSize: 16

    implicitHeight: Theme.controlHeight
    implicitWidth: Math.max(Theme.controlHeight * 2, contentRow.implicitWidth + Theme.space3 * 2)
    padding: 0

    readonly property bool isPrimary: variant === "primary"
    readonly property bool isDanger: variant === "danger"
    readonly property bool isGhost: variant === "ghost"

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
        }
    }

    ToolTip.visible: hovered && ToolTip.text !== ""
    ToolTip.delay: 500
    ToolTip.text: ""
}
