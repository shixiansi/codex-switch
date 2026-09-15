import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import theme

// Non-blocking notification stack anchored bottom-right.
Item {
    id: root

    property int maxVisible: 4
    property var items: []

    function push(message, level, detail) {
        var text = String(message === undefined || message === null ? "" : message)
        if (text === "")
            return
        var next = root.items.slice()
        next.push({
            "message": text,
            "detail": String(detail === undefined || detail === null ? "" : detail),
            "level": String(level || "info"),
            "stamp": Date.now()
        })
        while (next.length > root.maxVisible)
            next.shift()
        root.items = next
    }

    function dismiss(index) {
        var next = root.items.slice()
        if (index >= 0 && index < next.length)
            next.splice(index, 1)
        root.items = next
    }

    function clear() {
        root.items = []
    }

    implicitWidth: Math.min(420, parent ? parent.width - Theme.space5 * 2 : 420)
    implicitHeight: column.implicitHeight
    width: implicitWidth

    ColumnLayout {
        id: column
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        width: root.width
        spacing: Theme.space2

        Repeater {
            model: root.items

            delegate: Rectangle {
                id: toast

                required property var modelData
                required property int index

                readonly property string tone: {
                    var level = String(modelData.level || "info")
                    if (level === "error")
                        return "danger"
                    if (level === "success" || level === "warning" || level === "info")
                        return level
                    return "info"
                }

                Layout.fillWidth: true
                implicitHeight: toastLayout.implicitHeight + Theme.space3 * 2
                radius: Theme.radius
                color: Theme.surface
                border.width: Theme.borderWidth
                border.color: Qt.rgba(Theme.toneColor(tone).r, Theme.toneColor(tone).g, Theme.toneColor(tone).b, 0.4)
                opacity: 0
                x: 24

                Component.onCompleted: entry.start()

                ParallelAnimation {
                    id: entry
                    NumberAnimation {
                        target: toast
                        property: "opacity"
                        to: 1
                        duration: Theme.durationBase
                    }
                    NumberAnimation {
                        target: toast
                        property: "x"
                        to: 0
                        duration: Theme.durationBase
                        easing.type: Easing.OutCubic
                    }
                }

                Timer {
                    interval: toast.tone === "error" ? 8000 : 4500
                    running: true
                    onTriggered: root.dismiss(toast.index)
                }

                RowLayout {
                    id: toastLayout
                    anchors.fill: parent
                    anchors.margins: Theme.space3
                    spacing: Theme.space2

                    Rectangle {
                        Layout.alignment: Qt.AlignTop
                        width: 22
                        height: 22
                        radius: 11
                        color: Theme.toneSoftColor(toast.tone)

                        AppIcon {
                            anchors.centerIn: parent
                            name: toast.tone === "success" ? "check"
                                : toast.tone === "danger" ? "alert"
                                : toast.tone === "warning" ? "warning" : "pulse"
                            color: Theme.toneColor(toast.tone)
                            size: 13
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2

                        Text {
                            Layout.fillWidth: true
                            text: toast.modelData.message
                            color: Theme.text
                            font.pixelSize: Theme.fontBody
                            wrapMode: Text.WordWrap
                        }

                        Text {
                            Layout.fillWidth: true
                            text: toast.modelData.detail
                            color: Theme.textMuted
                            font.pixelSize: Theme.fontCaption
                            wrapMode: Text.WordWrap
                            visible: toast.modelData.detail !== ""
                            maximumLineCount: 4
                            elide: Text.ElideRight
                        }
                    }

                    AppIcon {
                        Layout.alignment: Qt.AlignTop
                        name: "close"
                        color: closeArea.containsMouse ? Theme.text : Theme.textFaint
                        size: 12

                        MouseArea {
                            id: closeArea
                            anchors.fill: parent
                            anchors.margins: -4
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.dismiss(toast.index)
                        }
                    }
                }

                MouseArea {
                    anchors.fill: parent
                    z: -1
                    onClicked: root.dismiss(toast.index)
                }
            }
        }
    }
}
