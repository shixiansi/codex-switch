import QtQuick
import QtQuick.Controls
import theme

// Styled toggle switch.
Switch {
    id: control

    implicitWidth: 40
    implicitHeight: 22

    indicator: Rectangle {
        implicitWidth: 40
        implicitHeight: 22
        x: 0
        y: (control.height - height) / 2
        radius: height / 2
        color: control.checked ? Theme.accent : Theme.surfaceActive
        border.width: Theme.borderWidth
        border.color: control.checked ? Theme.accent : Theme.border

        Behavior on color {
            ColorAnimation { duration: Theme.durationFast }
        }

        Rectangle {
            x: control.checked ? parent.width - width - 3 : 3
            y: 3
            width: 16
            height: 16
            radius: 8
            color: control.checked ? Theme.accentText : Theme.surface
            border.width: control.checked ? 0 : Theme.borderWidth
            border.color: Theme.borderStrong

            Behavior on x {
                NumberAnimation {
                    duration: Theme.durationFast
                    easing.type: Easing.OutCubic
                }
            }
        }
    }

    contentItem: Text {
        text: control.text
        color: Theme.text
        font.pixelSize: Theme.fontBody
        verticalAlignment: Text.AlignVCenter
        leftPadding: control.indicator.width + Theme.space2
        visible: control.text !== ""
    }

    HoverHandler {
        cursorShape: Qt.PointingHandCursor
    }
}
