import QtQuick
import QtQuick.Layouts
import theme

// Rendered whenever a list/panel has nothing to show.
//
// The root is a plain Item that stretches to its layout cell and centres an
// inner column. A Layout-type root (e.g. ColumnLayout) cannot be used here:
// declaring Layout.fillWidth both inside the component and at the call site
// conflicts, leaving the block at its implicit width so it hugs the left edge.
Item {
    id: root

    property string iconName: "list"
    property string title: "暂无数据"
    property string description: ""
    property string actionText: ""
    signal actionTriggered()

    Layout.fillWidth: true
    implicitHeight: inner.implicitHeight
    // Vertically centred within the available space when one is given.
    Layout.alignment: Qt.AlignVCenter

    ColumnLayout {
        id: inner
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        spacing: Theme.space2

        Item { Layout.preferredHeight: Theme.space4 }

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
            // Never wider than the available space, so narrow panels (e.g. the
            // account-pool column) do not push text outside the card.
            Layout.maximumWidth: Math.max(0, Math.min(360, inner.width - Theme.space4))
            text: root.title
            color: Theme.text
            font.pixelSize: Theme.fontSubtitle
            font.weight: Font.DemiBold
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
        }

        Text {
            Layout.alignment: Qt.AlignHCenter
            Layout.maximumWidth: Math.max(0, Math.min(360, inner.width - Theme.space4))
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

        Item { Layout.preferredHeight: Theme.space5 }
    }
}
