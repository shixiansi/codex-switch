import QtQuick
import QtQuick.Layouts
import theme

// Selectable list row with optional leading icon, badge and trailing meta.
Rectangle {
    id: root

    property string title: ""
    property string subtitle: ""
    property string meta: ""
    property string badgeText: ""
    property string badgeTone: "unknown"
    property string iconName: ""
    property bool selected: false
    property bool interactive: true
    // Exposed so callers can drive a ToolTip from the row's hover state.
    readonly property bool hovered: hover.containsMouse

    signal clicked()

    implicitHeight: Math.max(Theme.rowHeight + Theme.space2, layout.implicitHeight + Theme.space3)
    radius: Theme.radiusSm
    border.width: root.selected ? Theme.borderWidth : 0
    border.color: Theme.accent

    // Background is painted by an inner layer whose OPACITY is animated.
    //
    // Animating `color` between "transparent" and a solid tone looks like a
    // grey flash: "transparent" is rgba(0,0,0,0), so Qt interpolates from
    // BLACK, passing through a dark grey that is briefly visible. Fading a
    // pre-tinted rectangle avoids that entirely.
    color: "transparent"

    Rectangle {
        id: background
        anchors.fill: parent
        radius: root.radius
        color: root.selected ? Theme.accentSoft : Theme.surfaceHover
        opacity: root.selected ? 1 : (hover.containsMouse && root.interactive ? 1 : 0)

        Behavior on opacity {
            NumberAnimation {
                duration: Theme.durationFast
                easing.type: Easing.OutCubic
            }
        }
    }

    RowLayout {
        id: layout
        anchors.fill: parent
        anchors.margins: Theme.space2
        spacing: Theme.space2

        Rectangle {
            Layout.alignment: Qt.AlignVCenter
            width: 30
            height: 30
            radius: Theme.radiusSm
            color: root.selected ? Theme.surface : Theme.surfaceAlt
            visible: root.iconName !== ""

            AppIcon {
                anchors.centerIn: parent
                name: root.iconName
                color: root.selected ? Theme.accent : Theme.textMuted
                size: 16
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 1

            Text {
                Layout.fillWidth: true
                text: root.title
                color: Theme.text
                font.pixelSize: Theme.fontBody
                font.weight: root.selected ? Font.DemiBold : Font.Medium
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

        StatusBadge {
            Layout.alignment: Qt.AlignVCenter
            text: root.badgeText
            tone: root.badgeTone
            visible: root.badgeText !== ""
        }

        Text {
            Layout.alignment: Qt.AlignVCenter
            text: root.meta
            color: Theme.textFaint
            font.pixelSize: Theme.fontCaption
            elide: Text.ElideRight
            visible: root.meta !== ""
        }
    }

    MouseArea {
        id: hover
        anchors.fill: parent
        hoverEnabled: root.interactive
        cursorShape: root.interactive ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: {
            if (root.interactive)
                root.clicked()
        }
    }
}
