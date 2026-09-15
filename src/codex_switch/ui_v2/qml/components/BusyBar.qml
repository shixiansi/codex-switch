import QtQuick
import QtQuick.Layouts
import theme

// Indeterminate progress strip shown while a background task runs.
Item {
    id: root

    property bool running: false
    property string message: ""

    implicitHeight: root.running ? Theme.space1 : 0
    clip: true

    Rectangle {
        anchors.fill: parent
        color: Theme.accentSoft
        visible: root.running
    }

    Rectangle {
        id: bar
        width: parent.width * 0.32
        height: parent.height
        color: Theme.accent
        visible: root.running
        radius: height / 2

        SequentialAnimation on x {
            running: root.running
            loops: Animation.Infinite
            NumberAnimation {
                from: -bar.width
                to: root.width
                duration: 1100
                easing.type: Easing.InOutQuad
            }
        }
    }

    Behavior on implicitHeight {
        NumberAnimation { duration: Theme.durationFast }
    }
}
