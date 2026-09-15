import QtQuick
import QtQuick.Layouts
import theme

// Spinner plus caption for first-load and inline activity.
ColumnLayout {
    id: root

    property string message: "加载中 …"
    property int size: 26

    spacing: Theme.space2
    Layout.alignment: Qt.AlignHCenter

    Item {
        Layout.alignment: Qt.AlignHCenter
        Layout.preferredWidth: root.size
        Layout.preferredHeight: root.size

        Rectangle {
            id: track
            anchors.fill: parent
            radius: width / 2
            color: "transparent"
            border.width: 3
            border.color: Theme.surfaceActive
        }

        Rectangle {
            anchors.fill: parent
            radius: width / 2
            color: "transparent"
            border.width: 3
            border.color: Theme.accent

            // Quarter arc: hide all but one quadrant.
            Rectangle {
                anchors.right: parent.right
                anchors.top: parent.top
                width: parent.width / 2
                height: parent.height / 2
                color: Theme.surface
            }

            RotationAnimator on rotation {
                running: root.visible
                loops: Animation.Infinite
                from: 0
                to: 360
                duration: 900
            }
        }
    }

    Text {
        Layout.alignment: Qt.AlignHCenter
        text: root.message
        color: Theme.textMuted
        font.pixelSize: Theme.fontCaption
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.WordWrap
    }
}
