import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import theme

// Right-hand drawer for details and editing. Slides in, dims the content
// behind it, and closes on Escape or overlay click.
Item {
    id: root

    property bool open: false
    property string title: ""
    property string subtitle: ""
    // Named `drawerWidth` because Item.width is FINAL in Qt.
    property int drawerWidth: Theme.drawerWidth

    default property alias content: body.data

    signal closed()

    anchors.fill: parent
    visible: overlay.opacity > 0.01
    z: 100

    onOpenChanged: {
        if (!open)
            root.closed()
    }

    // Dimming layer that also captures clicks.
    Rectangle {
        id: overlay
        anchors.fill: parent
        color: Theme.overlay
        opacity: root.open ? 1 : 0

        Behavior on opacity {
            NumberAnimation { duration: Theme.durationBase }
        }

        MouseArea {
            anchors.fill: parent
            onClicked: root.open = false
        }
    }

    Rectangle {
        id: panel
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.right: parent.right
        width: Math.min(root.drawerWidth, root.width * 0.92)
        color: Theme.surface
        border.width: Theme.borderWidth
        border.color: Theme.border
        x: root.open ? 0 : width

        Behavior on x {
            NumberAnimation {
                duration: Theme.durationBase
                easing.type: Easing.OutCubic
            }
        }

        MouseArea {
            anchors.fill: parent
        }

        ColumnLayout {
            anchors.fill: parent
            spacing: 0

            // Header
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: headerLayout.implicitHeight + Theme.space3 * 2
                color: Theme.surface
                border.width: Theme.borderWidth
                border.color: Theme.border

                RowLayout {
                    id: headerLayout
                    anchors.fill: parent
                    anchors.margins: Theme.space3
                    spacing: Theme.space2

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 1

                        Text {
                            Layout.fillWidth: true
                            text: root.title
                            color: Theme.text
                            font.pixelSize: Theme.fontTitle
                            font.weight: Font.DemiBold
                            elide: Text.ElideRight
                        }

                        Text {
                            Layout.fillWidth: true
                            text: root.subtitle
                            color: Theme.textMuted
                            font.pixelSize: Theme.fontCaption
                            elide: Text.ElideRight
                            visible: root.subtitle !== ""
                        }
                    }

                    AppButton {
                        text: "关闭"
                        iconName: "close"
                        variant: "ghost"
                        onClicked: root.open = false
                    }
                }
            }

            // Body
            Flickable {
                id: scroller
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                contentWidth: width
                contentHeight: body.implicitHeight + Theme.space4 * 2
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                ColumnLayout {
                    id: body
                    x: Theme.space4
                    y: Theme.space4
                    width: scroller.width - Theme.space4 * 2
                    spacing: Theme.space3
                }
            }
        }

        // Slide-in shadow line
        Rectangle {
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: 1
            color: Theme.border
        }
    }

    Shortcut {
        sequence: "Escape"
        enabled: root.open
        onActivated: root.open = false
    }
}
