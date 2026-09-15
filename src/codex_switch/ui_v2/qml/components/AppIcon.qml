import QtQuick
import QtQuick.Effects
import theme

// Renders a bundled monochrome SVG tinted to any theme colour.
Item {
    id: root

    property string name: ""
    property color color: Theme.textMuted
    property int size: 18
    property real opacityValue: 1.0

    implicitWidth: size
    implicitHeight: size

    Image {
        id: image
        anchors.fill: parent
        source: Icons.source(root.name)
        sourceSize.width: root.size * 2
        sourceSize.height: root.size * 2
        fillMode: Image.PreserveAspectFit
        visible: false
        asynchronous: true
    }

    MultiEffect {
        anchors.fill: parent
        source: image
        colorization: 1.0
        colorizationColor: root.color
        opacity: root.opacityValue
    }
}
