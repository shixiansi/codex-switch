import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import theme
import components

// 模型测试: batch test the selected profile's models, plus a one-shot chat test.
RowLayout {
    id: panel

    spacing: Theme.space3

    // -- batch results --
    AppCard {
        Layout.fillWidth: true
        Layout.fillHeight: true
        title: "模型批量测试"
        subtitle: toolsModel.chat.profileName || "未选择配置"
        iconName: "pulse"

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space2

            AppButton {
                text: app.busy ? "测试中 …" : "开始测试"
                iconName: "pulse"
                variant: "primary"
                enabled: !app.busy
                onClicked: toolsModel.runBatchTest()
            }

            AppButton {
                text: "取消"
                visible: app.busy
                onClicked: toolsModel.cancelBatchTest()
            }

            Item { Layout.fillWidth: true }

            Text {
                text: (toolsModel.batch.successCount || 0) + " 成功 · "
                    + (toolsModel.batch.errorCount || 0) + " 失败"
                color: Theme.textMuted
                font.pixelSize: Theme.fontCaption
                visible: toolsModel.batch.exists === true
            }
        }

        Text {
            Layout.fillWidth: true
            text: "测试时间：" + (toolsModel.batch.testedAt || "尚未测试")
            color: Theme.textFaint
            font.pixelSize: Theme.fontCaption
        }

        EmptyState {
            Layout.fillWidth: true
            visible: !toolsModel.batch.exists
            iconName: "pulse"
            title: "暂无测试结果"
            description: "先执行健康检测以获取模型列表，然后开始批量测试。"
        }

        ListView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            visible: toolsModel.batch.exists === true
            model: toolsModel.batch.results || []
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            delegate: ListRow {
                id: resultRow

                required property var modelData

                width: parent ? parent.width : 0
                interactive: false
                iconName: modelData.status === "success" ? "check" : "alert"
                title: modelData.model
                subtitle: modelData.detail
                badgeText: modelData.status === "success" ? "可用"
                    : modelData.status === "error" ? "失败" : "等待"
                badgeTone: modelData.tone
                meta: modelData.durationMs === null || modelData.durationMs === undefined
                    ? "" : (modelData.durationMs + " ms")

                // 列表只显示单行摘要；被省略的完整内容（例如接口返回的原始 JSON）
                // 通过悬停提示查看，避免撑爆布局又保留排查信息。
                ToolTip.visible: resultRow.hovered
                    && modelData.detailFull !== undefined
                    && modelData.detailFull !== modelData.detail
                ToolTip.delay: 400
                ToolTip.text: modelData.detailFull || ""
            }
        }
    }

    // -- chat test --
    AppCard {
        Layout.fillWidth: true
        Layout.fillHeight: true
        title: "聊天测试"
        subtitle: toolsModel.chat.available ? toolsModel.chat.profileName : "未选择配置"
        iconName: "terminal"

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space2

            AppComboBox {
                id: modelPicker
                Layout.fillWidth: true
                options: {
                    var list = []
                    var models = toolsModel.chat.models || []
                    for (var i = 0; i < models.length; i++)
                        list.push({ value: models[i], label: models[i] })
                    return list
                }
                selectedValue: toolsModel.chat.models && toolsModel.chat.models.length > 0
                    ? toolsModel.chat.models[0] : ""
            }

            AppComboBox {
                id: wirePicker
                Layout.preferredWidth: 170
                options: {
                    var list = []
                    var wires = toolsModel.chat.wireApiChoices || []
                    for (var i = 0; i < wires.length; i++)
                        list.push({ value: wires[i], label: wires[i] })
                    return list
                }
                selectedValue: toolsModel.chat.wireApi || "responses"
            }
        }

        ListView {
            id: chatList
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: toolsModel.chat.messages || []
            spacing: Theme.space2
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            onCountChanged: Qt.callLater(function () { chatList.positionViewAtEnd() })

            delegate: Rectangle {
                required property var modelData

                width: chatList.width
                implicitHeight: messageText.implicitHeight + Theme.space2 * 2
                radius: Theme.radiusSm
                color: modelData.role === "user" ? Theme.accentSoft : Theme.surfaceAlt

                Text {
                    id: messageText
                    anchors.fill: parent
                    anchors.margins: Theme.space2
                    text: modelData.text
                    color: Theme.text
                    font.pixelSize: Theme.fontBody
                    wrapMode: Text.WordWrap
                    textFormat: Text.PlainText
                }
            }
        }

        EmptyState {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: !toolsModel.chat.messages || toolsModel.chat.messages.length === 0
            iconName: "terminal"
            title: "暂无对话"
            description: "输入一条测试消息，检查当前配置的接口是否可用。"
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space2

            AppTextField {
                id: promptField
                Layout.fillWidth: true
                placeholderText: "输入测试消息，例如：ping"
                onAccepted: sendButton.send()
            }

            AppButton {
                id: sendButton
                text: "发送"
                variant: "primary"
                enabled: !app.busy && promptField.text !== ""

                function send() {
                    if (promptField.text === "")
                        return
                    toolsModel.sendChat(promptField.text, modelPicker.selectedValue, wirePicker.selectedValue)
                    promptField.text = ""
                }

                onClicked: send()
            }

            AppButton {
                text: "清空"
                variant: "ghost"
                onClicked: toolsModel.clearChat()
            }
        }
    }
}
