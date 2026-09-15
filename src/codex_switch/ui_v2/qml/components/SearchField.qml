import QtQuick
import QtQuick.Controls
import theme

// Rounded search input with a leading icon and a clear button.
TextField {
    id: control

    property string placeholder: "搜索"

    implicitHeight: Theme.controlHeight
    leftPadding: Theme.space5 + Theme.space1
    rightPadding: clearButton.visible ? Theme.space5 : Theme.space3
    font.pixelSize: Theme.fontBody
    color: Theme.text
    placeholderText: placeholder
    placeholderTextColor: Theme.textFaint
    selectByMouse: true
    verticalAlignment: TextInput.AlignVCenter
    selectionColor: Theme.accent
    selectedTextColor: Theme.accentText

    background: Rectangle {
        radius: Theme.radiusSm
        color: Theme.surface
        border.width: Theme.borderWidth
        border.color: control.activeFocus ? Theme.accent : Theme.border

        Behavior on border.color {
            ColorAnimation { duration: Theme.durationFast }
        }
    }

    AppIcon {
        anchors.left: parent.left
        anchors.leftMargin: Theme.space2 + 2
        anchors.verticalCenter: parent.verticalCenter
        name: "search"
        color: control.activeFocus ? Theme.accent : Theme.textFaint
        size: 15
    }

    AppIcon {
        id: clearButton
        anchors.right: parent.right
        anchors.rightMargin: Theme.space2
        anchors.verticalCenter: parent.verticalCenter
        name: "close"
        color: clearHover.containsMouse ? Theme.text : Theme.textFaint
        size: 13
        visible: control.text !== ""

        MouseArea {
            id: clearHover
            anchors.fill: parent
            anchors.margins: -4
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: {
                control.text = ""
                control.forceActiveFocus()
            }
        }
    }
}
