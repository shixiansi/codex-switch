import QtQuick
import theme

// Small status pill. Tone drives the colour pair; text is caller-supplied.
Rectangle {
    id: root

    property string text: ""
    property string tone: "unknown"
    property bool showDot: false

    implicitWidth: content.implicitWidth + Theme.space2 * 2
    implicitHeight: Math.max(20, Theme.fontCaption + Theme.space2)

    radius: height / 2
    color: Theme.toneSoftColor(tone)
    border.width: Theme.borderWidth
    border.color: Qt.rgba(Theme.toneColor(tone).r, Theme.toneColor(tone).g, Theme.toneColor(tone).b, 0.28)

    Row {
        id: content
        anchors.centerIn: parent
        spacing: Theme.space1 + 2

        Rectangle {
            width: 6
            height: 6
            radius: 3
            color: Theme.toneColor(root.tone)
            visible: root.showDot
            anchors.verticalCenter: parent.verticalCenter
        }

        Text {
            text: root.text
            color: Theme.toneColor(root.tone)
            font.pixelSize: Theme.fontCaption
            font.weight: Font.Medium
            anchors.verticalCenter: parent.verticalCenter
        }
    }
}
