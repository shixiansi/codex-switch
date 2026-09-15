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

    readonly property color _bg: {
        if (isPrimary)
            return control.down ? Qt.darker(Theme.accent, 1.15) : (control.hovered ? Theme.accentHover : Theme.accent)
        if (isDanger)
            return control.down ? Qt.darker(Theme.danger, 1.15) : (control.hovered ? Qt.lighter(Theme.danger, 1.06) : Theme.danger)
        if (isGhost)
            return control.down ? Theme.surfaceActive : (control.hovered ? Theme.surfaceHover : "transparent")
        return control.down ? Theme.surfaceActive : (control.hovered ? Theme.surfaceHover : Theme.surface)
    }

    readonly property color _fg: {
        if (isPrimary)
            return Theme.accentText
        if (isDanger)
            return "#FFFFFF"
        return control.hovered || control.down ? Theme.text : Theme.textMuted
    }

    readonly property color _borderColor: isPrimary || isDanger ? "transparent" : Theme.border

    background: Rectangle {
        radius: Theme.radiusSm
        color: control._bg
        border.width: control.isGhost ? 0 : Theme.borderWidth
        border.color: control._borderColor

        Behavior on color {
            ColorAnimation { duration: Theme.durationFast }
        }
    }

    contentItem: Row {
        id: contentRow
        spacing: Theme.space1 + 2
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

    ToolTip.visible: hovered && ToolTip.text !== ""
    ToolTip.delay: 500
    ToolTip.text: ""
}
