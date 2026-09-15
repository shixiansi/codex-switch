import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import theme

// Presentational confirmation dialog for destructive actions.
//
// It holds NO callbacks: the pending action lives in Python
// (AppController.pendingConfirm) so a single instance in AppShell serves every
// page. Callers bind `confirm` and invoke `confirmed` / `cancelled`.
//
// Escape and clicking outside cancel. There is no Enter shortcut, so a stray
// keypress cannot confirm a delete. When `confirm.warning` is set the action is
// blocked and the confirm button hidden, which lets callers explain why.
Popup {
    id: root

    // Spec produced by AppController.pendingConfirm:
    // { title, message, detail, warning, confirmText, danger }
    property var confirm: ({})

    signal confirmed()
    signal cancelled()

    readonly property bool blocked: String(confirm.warning || "") !== ""

    modal: true
    focus: true
    anchors.centerIn: parent
    width: Math.min(460, parent ? parent.width - Theme.space6 * 2 : 460)
    padding: Theme.space4
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    onClosed: root.cancelled()

    background: Rectangle {
        radius: Theme.radius
        color: Theme.surface
        border.width: Theme.borderWidth
        border.color: Theme.border
    }

    contentItem: ColumnLayout {
        spacing: Theme.space3

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space2

            Rectangle {
                Layout.alignment: Qt.AlignTop
                width: 28
                height: 28
                radius: 14
                color: root.blocked ? Theme.warningSoft
                    : root.confirm.danger === false ? Theme.accentSoft : Theme.dangerSoft

                AppIcon {
                    anchors.centerIn: parent
                    name: root.blocked || root.confirm.danger !== false ? "warning" : "alert"
                    color: root.blocked ? Theme.warning
                        : root.confirm.danger === false ? Theme.accent : Theme.danger
                    size: 16
                }
            }

            Text {
                Layout.fillWidth: true
                text: root.confirm.title || "确认操作"
                color: Theme.text
                font.pixelSize: Theme.fontSubtitle
                font.weight: Font.DemiBold
                wrapMode: Text.WordWrap
            }
        }

        Text {
            Layout.fillWidth: true
            text: root.confirm.message || ""
            color: Theme.text
            font.pixelSize: Theme.fontBody
            wrapMode: Text.WordWrap
            visible: String(root.confirm.message || "") !== ""
        }

        Text {
            Layout.fillWidth: true
            text: root.confirm.detail || ""
            color: Theme.textMuted
            font.pixelSize: Theme.fontCaption
            wrapMode: Text.WordWrap
            visible: String(root.confirm.detail || "") !== ""
        }

        // Blocking reason: boxed so it cannot be missed.
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: warningText.implicitHeight + Theme.space2 * 2
            radius: Theme.radiusSm
            color: Theme.warningSoft
            border.width: Theme.borderWidth
            border.color: Qt.rgba(Theme.warning.r, Theme.warning.g, Theme.warning.b, 0.35)
            visible: root.blocked

            Text {
                id: warningText
                anchors.fill: parent
                anchors.margins: Theme.space2
                text: root.confirm.warning || ""
                color: Theme.warning
                font.pixelSize: Theme.fontCaption
                wrapMode: Text.WordWrap
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.topMargin: Theme.space1
            spacing: Theme.space2

            Item { Layout.fillWidth: true }

            AppButton {
                text: root.blocked ? "知道了" : "取消"
                variant: root.blocked ? "primary" : "ghost"
                onClicked: root.close()
            }

            AppButton {
                text: root.confirm.confirmText || "删除"
                variant: root.confirm.danger === false ? "primary" : "danger"
                visible: !root.blocked
                onClicked: {
                    root.confirmed()
                    root.close()
                }
            }
        }
    }
}
