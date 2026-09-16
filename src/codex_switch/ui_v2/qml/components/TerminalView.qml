import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import theme

// 终端渲染视图：可选项条 + 输出区 + 输入栏。
//
// 主区与放大浮窗共用同一实现（DRY），各自通过信号把输入/选择回传给上层，
// 由上层决定发给哪个会话。
Item {
    id: root

    property string screenText: ""
    property bool awaitingChoice: false
    property var choices: []
    property bool inputEnabled: true
    property string placeholder: "输入并回车发送给 AI CLI …"

    signal inputSubmitted(string text)
    signal choiceSelected(int index)

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // ---- 可选项条：检测到 CLI 等待选择时浮出 ----
        Rectangle {
            Layout.fillWidth: true
            Layout.bottomMargin: visible ? Theme.space2 : 0
            visible: root.awaitingChoice && root.choices.length > 0
            implicitHeight: visible ? choiceRow.implicitHeight + Theme.space2 * 2 : 0
            radius: Theme.radiusSm
            color: Theme.accentSoft
            border.width: Theme.borderWidth
            border.color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.35)

            RowLayout {
                id: choiceRow
                anchors.fill: parent
                anchors.margins: Theme.space2
                spacing: Theme.space2

                AppIcon {
                    name: "alert"
                    color: Theme.accent
                    size: 15
                }

                Text {
                    text: "等待你的选择"
                    color: Theme.accent
                    font.pixelSize: Theme.fontCaption
                    font.weight: Font.Medium
                }

                Repeater {
                    model: root.choices

                    delegate: AppButton {
                        required property var modelData
                        required property int index

                        text: modelData
                        variant: "primary"
                        onClicked: root.choiceSelected(index)
                    }
                }

                Item { Layout.fillWidth: true }
            }
        }

        // ---- 输出区 ----
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            radius: Theme.radiusSm
            color: Theme.codeBg
            border.width: Theme.borderWidth
            border.color: Theme.border

            Flickable {
                id: flick

                anchors.fill: parent
                anchors.margins: Theme.space2
                contentWidth: width
                contentHeight: outputText.implicitHeight
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                // 自动跟随最新输出，但用户向上滚动查看历史时立刻停止跟随；
                // 滚回底部则恢复跟随。程序化滚动落在底部，因此会保持吸底。
                property bool pinnedToBottom: true
                onContentYChanged: pinnedToBottom = contentY >= contentHeight - height - 2
                onContentHeightChanged: {
                    if (pinnedToBottom)
                        contentY = Math.max(0, contentHeight - height)
                }

                Text {
                    id: outputText

                    width: parent.width
                    text: root.screenText !== "" ? root.screenText : "（暂无输出）"
                    color: root.screenText !== "" ? Theme.text : Theme.textFaint
                    font.family: "Consolas, Menlo, Monaco, monospace"
                    font.pixelSize: 13
                    wrapMode: Text.WrapAnywhere
                }
            }
        }

        // ---- 输入栏 ----
        RowLayout {
            Layout.fillWidth: true
            Layout.topMargin: Theme.space2
            spacing: Theme.space2

            AppTextField {
                id: inputField

                Layout.fillWidth: true
                enabled: root.inputEnabled
                placeholderText: root.placeholder
                onAccepted: {
                    if (text !== "") {
                        root.inputSubmitted(text)
                        text = ""
                    }
                }
            }

            AppButton {
                text: "发送"
                iconName: "chevron-right"
                variant: "primary"
                enabled: root.inputEnabled && inputField.text !== ""
                onClicked: {
                    root.inputSubmitted(inputField.text)
                    inputField.text = ""
                }
            }
        }
    }
}
