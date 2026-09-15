import QtQuick
import QtQuick.Layouts
import theme

// Rendered whenever a list/panel has nothing to show.
ColumnLayout {
    id: root

    property string iconName: "list"
    property string title: "暂无数据"
    property string description: ""
    property string actionText: ""
    signal actionTriggered()

    spacing: Theme.space2
    Layout.fillWidth: true

    Item { Layout.fillHeight: true; Layout.preferredHeight: Theme.space4 }

    Rectangle {
        Layout.alignment: Qt.AlignHCenter
        width: 48
        height: 48
        radius: 24
        color: Theme.surfaceAlt

        AppIcon {
            anchors.centerIn: parent
            name: root.iconName
            color: Theme.textFaint
            size: 22
        }
    }

    Text {
        Layout.alignment: Qt.AlignHCenter
        text: root.title
        color: Theme.text
        font.pixelSize: Theme.fontSubtitle
        font.weight: Font.DemiBold
    }

    Text {
        Layout.alignment: Qt.AlignHCenter
        Layout.maximumWidth: 360
        text: root.description
        color: Theme.textMuted
        font.pixelSize: Theme.fontCaption
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.WordWrap
        visible: root.description !== ""
    }

    AppButton {
        Layout.alignment: Qt.AlignHCenter
        Layout.topMargin: Theme.space2
        text: root.actionText
        variant: "primary"
        visible: root.actionText !== ""
        onClicked: root.actionTriggered()
    }

    Item { Layout.fillHeight: true; Layout.preferredHeight: Theme.space5 }
}
