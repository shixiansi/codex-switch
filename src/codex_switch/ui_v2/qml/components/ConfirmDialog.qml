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
//
// An optional third button is available via `confirm.extraText` (emitting
// `extraConfirmed`). Only the terminal risk-review flow uses it, for "allow
// this kind for the session"; it stays hidden everywhere else.
Popup {
    id: root

    // Spec produced by AppController.pendingConfirm:
    // { title, message, detail, warning, confirmText, danger, extraText }
    property var confirm: ({})

    signal confirmed()
    signal cancelled()
    signal extraConfirmed()

    readonly property bool blocked: String(confirm.warning || "") !== ""

    // Whether the close was caused by pressing an action button.
    //
    // `onClosed` fires for every close path, so without this flag pressing
    // "confirm" would also emit `cancelled`. That matters now that a caller
    // attaches meaning to dismissal (the terminal review treats cancel as
    // deny): answering one review can synchronously present the next one, and
    // the trailing `cancelled` would immediately deny that next review.
    property bool actionTaken: false

    modal: true
    focus: true
    anchors.centerIn: parent
    width: Math.min(460, parent ? parent.width - Theme.space6 * 2 : 460)
    padding: Theme.space4
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    onClosed: {
        if (!root.actionTaken)
            root.cancelled()
        root.actionTaken = false
    }

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
                text: String(root.confirm.extraText || "")
                variant: "secondary"
                visible: !root.blocked && String(root.confirm.extraText || "") !== ""
                onClicked: {
                    // Do NOT call close() here: the controller clears its spec,
                    // which drives the close through onConfirmChanged. Closing
                    // explicitly would race with a *newly presented* prompt
                    // (answering one terminal review can present the next one
                    // synchronously) and close it again immediately.
                    root.actionTaken = true
                    root.extraConfirmed()
                }
            }

            AppButton {
                text: root.confirm.confirmText || "删除"
                variant: root.confirm.danger === false ? "primary" : "danger"
                visible: !root.blocked
                onClicked: {
                    // See the note above: the controller owns the close.
                    root.actionTaken = true
                    root.confirmed()
                }
            }
        }
    }
}
