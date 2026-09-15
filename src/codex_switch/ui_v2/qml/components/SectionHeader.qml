import QtQuick
import QtQuick.Layouts
import theme

// Page title block with optional actions on the right.
RowLayout {
    id: root

    property string title: ""
    property string description: ""

    default property alias actionItems: actions.data

    Layout.fillWidth: true
    spacing: Theme.space3

    ColumnLayout {
        Layout.fillWidth: true
        spacing: 2

        Text {
            Layout.fillWidth: true
            text: root.title
            color: Theme.text
            font.pixelSize: Theme.fontDisplay
            font.weight: Font.DemiBold
            elide: Text.ElideRight
        }

        Text {
            Layout.fillWidth: true
            text: root.description
            color: Theme.textMuted
            font.pixelSize: Theme.fontBody
            wrapMode: Text.WordWrap
            visible: root.description !== ""
        }
    }

    RowLayout {
        id: actions
        Layout.alignment: Qt.AlignTop
        spacing: Theme.space2
    }
}
