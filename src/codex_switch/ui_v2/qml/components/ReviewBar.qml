import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import theme

// 风险审查提示条：展示待授权的菜单并收集用户的三个决定。
//
// 为什么需要它（而不只有全局弹窗）：授权弹窗挂在主窗口上，而"放大"是一个
// 独立的顶层 Window——模态弹窗无法覆盖到另一个顶层窗口。若只有弹窗，用户在
// 放大窗口里工作时会完全看不到授权请求，直到超时被按拒绝处理。
// 因此放大窗口用这条内嵌提示条；主窗口用弹窗（见 AppShell.qml）。
//
// 组件不做任何判定：策略、超时与"是否已问过"都在 Python 侧，这里只负责
// 展示与回传信号。
ColumnLayout {
    id: root

    // 待授权项：{ title, label, payload, prompt, reason, risk, riskLabel, ... }
    property var review: ({})
    property int remainingSeconds: 0

    signal approveRequested()
    signal allowKindRequested()
    signal denyRequested()

    readonly property string riskLabel: String(review.riskLabel || "")
    readonly property bool risky: String(review.risk || "") === "risky"
    readonly property var accentColor: risky ? Theme.danger : Theme.warning
    readonly property var softColor: risky ? Theme.dangerSoft : Theme.warningSoft

    spacing: Theme.space2

    Rectangle {
        Layout.fillWidth: true
        implicitHeight: barColumn.implicitHeight + Theme.space3 * 2
        radius: Theme.radiusSm
        color: root.softColor
        border.width: Theme.borderWidth
        border.color: Qt.rgba(root.accentColor.r, root.accentColor.g, root.accentColor.b, 0.35)

        ColumnLayout {
            id: barColumn

            anchors.fill: parent
            anchors.margins: Theme.space3
            spacing: Theme.space2

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.space2

                AppIcon {
                    name: "alert"
                    color: root.accentColor
                    size: 16
                }

                Text {
                    Layout.fillWidth: true
                    text: "需要你授权　·　" + String(root.review.title || "会话")
                        + (root.riskLabel !== "" ? "　·　" + root.riskLabel : "")
                    color: root.accentColor
                    font.pixelSize: Theme.fontBody
                    font.weight: Font.DemiBold
                    wrapMode: Text.WordWrap
                }

                Text {
                    visible: root.remainingSeconds > 0
                    text: root.remainingSeconds + "s 后按拒绝处理"
                    color: Theme.textMuted
                    font.pixelSize: Theme.fontCaption
                }
            }

            // 将要替你按下的内容——用户最需要先看到这一行。
            Text {
                Layout.fillWidth: true
                text: "将自动发送："
                    + (String(root.review.label || "") !== ""
                        ? String(root.review.label)
                        : String(root.review.payload || ""))
                color: Theme.text
                font.pixelSize: Theme.fontBody
                font.weight: Font.Medium
                wrapMode: Text.WordWrap
            }

            // CLI 的原始提示行：confirm 型菜单的风险信息全在这里。
            Text {
                Layout.fillWidth: true
                visible: String(root.review.prompt || "") !== ""
                text: "屏幕提示：" + String(root.review.prompt || "")
                color: Theme.textMuted
                font.pixelSize: Theme.fontCaption
                font.family: "Consolas, Menlo, Monaco, monospace"
                wrapMode: Text.WordWrap
            }

            Text {
                Layout.fillWidth: true
                visible: String(root.review.reason || "") !== ""
                text: "判定理由：" + String(root.review.reason || "")
                color: Theme.textMuted
                font.pixelSize: Theme.fontCaption
                wrapMode: Text.WordWrap
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.space2

                Item { Layout.fillWidth: true }

                AppButton {
                    text: "拒绝"
                    variant: "secondary"
                    onClicked: root.denyRequested()

                    ToolTip.visible: hovered
                    ToolTip.delay: 400
                    ToolTip.text: "不发送任何按键，且本会话不再提示这个菜单"
                }
                AppButton {
                    text: "本会话允许此类"
                    variant: "ghost"
                    onClicked: root.allowKindRequested()

                    ToolTip.visible: hovered
                    ToolTip.delay: 400
                    ToolTip.text: "本会话内同类菜单不再询问（不会保存到下次启动）"
                }
                AppButton {
                    text: "允许本次"
                    variant: root.risky ? "danger" : "primary"
                    onClicked: root.approveRequested()

                    ToolTip.visible: hovered
                    ToolTip.delay: 400
                    ToolTip.text: "只发送这一次；下一个菜单仍会询问"
                }
            }
        }
    }
}
