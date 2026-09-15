import QtQuick
import QtQuick.Layouts
import theme

// Metric tile: label, large value, hint and a tone-coloured icon.
Rectangle {
    id: root

    property string label: ""
    property string value: ""
    property string hint: ""
    property string iconName: ""
    property string tone: "info"

    implicitHeight: layout.implicitHeight + Theme.space3 * 2
    implicitWidth: 200
    radius: Theme.radius
    color: Theme.surface
    border.width: Theme.borderWidth
    border.color: Theme.border

    ColumnLayout {
        id: layout
        anchors.fill: parent
        anchors.margins: Theme.space3
        spacing: Theme.space1

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space2

            Rectangle {
                width: 28
                height: 28
                radius: Theme.radiusSm
                color: Theme.toneSoftColor(root.tone)

                AppIcon {
                    anchors.centerIn: parent
                    name: root.iconName
                    color: Theme.toneColor(root.tone)
                    size: 16
                }
            }

            Text {
                text: root.label
                color: Theme.textMuted
                font.pixelSize: Theme.fontCaption
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignVCenter
                elide: Text.ElideRight
            }
        }

        Text {
            text: root.value
            color: Theme.text
            font.pixelSize: Theme.fontDisplay
            font.weight: Font.DemiBold
            Layout.fillWidth: true
            elide: Text.ElideRight
            Layout.topMargin: Theme.space1
        }

        Text {
            text: root.hint
            color: Theme.textFaint
            font.pixelSize: Theme.fontCaption
            Layout.fillWidth: true
            elide: Text.ElideRight
            visible: root.hint !== ""
        }
    }
}
