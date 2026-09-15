import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import theme

// Bordered surface used for every content block. Low elevation, light border.
Rectangle {
    id: root

    property string title: ""
    property string subtitle: ""
    property string iconName: ""
    property bool collapsible: false
    property bool expanded: true

    // Children are laid out vertically inside the card body.
    default property alias content: body.data

    implicitHeight: layout.implicitHeight + Theme.space4 * 2
    radius: Theme.radius
    color: Theme.surface
    border.width: Theme.borderWidth
    border.color: Theme.border

    ColumnLayout {
        id: layout
        anchors.fill: parent
        anchors.margins: Theme.space4
        spacing: Theme.space3

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space2
            visible: root.title !== "" || root.iconName !== ""

            AppIcon {
                name: root.iconName
                color: Theme.accent
                size: 16
                visible: root.iconName !== ""
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 1

                Text {
                    text: root.title
                    color: Theme.text
                    font.pixelSize: Theme.fontSubtitle
                    font.weight: Font.DemiBold
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                    visible: root.title !== ""
                }

                Text {
                    text: root.subtitle
                    color: Theme.textMuted
                    font.pixelSize: Theme.fontCaption
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    visible: root.subtitle !== ""
                }
            }

            AppIcon {
                name: "chevron-right"
                color: Theme.textFaint
                size: 16
                rotation: root.expanded ? 90 : 0
                visible: root.collapsible

                Behavior on rotation {
                    NumberAnimation { duration: Theme.durationFast }
                }

                MouseArea {
                    anchors.fill: parent
                    anchors.margins: -Theme.space1
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.expanded = !root.expanded
                }
            }
        }

        ColumnLayout {
            id: body
            Layout.fillWidth: true
            spacing: Theme.space2
            visible: root.expanded
        }
    }
}
