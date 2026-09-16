import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import theme
import components

Page {
    id: root

    background: Rectangle { color: Theme.bg }

    // 新建会话抽屉状态
    property bool creating: false
    property string newTitle: ""
    property string newCommand: "codex"
    property string newCwd: ""
    // 按项目打开
    property string newProjectId: ""
    property string newProjectClient: "codex"

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // ================= 左侧：会话总览 =================
        Rectangle {
            Layout.preferredWidth: 300
            Layout.fillHeight: true
            color: Theme.surface
            border.width: Theme.borderWidth
            border.color: Theme.border

            ColumnLayout {
                anchors.fill: parent
                spacing: Theme.space2

                // 顶栏：标题 + 新建 + 清理残留
                RowLayout {
                    Layout.fillWidth: true
                    Layout.margins: Theme.space3
                    spacing: Theme.space2

                    Text {
                        text: "AI 终端"
                        color: Theme.text
                        font.pixelSize: Theme.fontTitle
                        font.weight: Font.DemiBold
                    }

                    Item { Layout.fillWidth: true }

                    AppButton {
                        text: "新建"
                        iconName: "terminal"
                        variant: "primary"
                        onClicked: createPopup.open()
                    }

                    AppButton {
                        text: "清理残留 (" + terminalModel.runningCount + ")"
                        iconName: "refresh"
                        variant: "ghost"
                        onClicked: terminalModel.cleanupOrphans()
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 1
                    color: Theme.border
                }

                // 会话卡片列表
                ListView {
                    id: sessionList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    model: terminalModel.sessions
                    spacing: Theme.space2
                    anchors.leftMargin: Theme.space2
                    anchors.rightMargin: Theme.space2

                    delegate: Rectangle {
                        id: card
                        required property var modelData
                        width: sessionList.width
                        implicitHeight: 64
                        radius: Theme.radiusSm
                        color: terminalModel.activeId === modelData.sessionId ? Theme.accentSoft : Theme.surfaceAlt
                        border.width: Theme.borderWidth
                        border.color: terminalModel.activeId === modelData.sessionId ? Theme.accent : Theme.border

                        MouseArea {
                            anchors.fill: parent
                            onClicked: terminalModel.focus(modelData.sessionId)
                        }

                        RowLayout {
                            anchors.fill: parent
                            anchors.margins: Theme.space2
                            spacing: Theme.space2

                            Rectangle {
                                width: 8
                                height: 8
                                radius: 4
                                color: {
                                    switch (modelData.status) {
                                    case "running": return Theme.accent
                                    case "completed": return Theme.success
                                    case "failed": return Theme.danger
                                    case "stopped": return Theme.unknown
                                    default: return Theme.unknown
                                    }
                                }
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2
                                Text {
                                    Layout.fillWidth: true
                                    text: modelData.title
                                    color: Theme.text
                                    font.pixelSize: Theme.fontBody
                                    font.weight: Font.Medium
                                    elide: Text.ElideRight
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: modelData.statusLabel + (modelData.lastLine ? " · " + modelData.lastLine : "")
                                    color: Theme.textFaint
                                    font.pixelSize: Theme.fontCaption
                                    elide: Text.ElideRight
                                }
                            }

                            AppButton {
                                text: "停止"
                                iconName: "close"
                                variant: "ghost"
                                visible: modelData.status === "running"
                                onClicked: terminalModel.stopSession(modelData.sessionId)
                            }
                            AppButton {
                                text: "放大"
                                iconName: "expand"
                                variant: "ghost"
                                visible: modelData.status === "running"
                                onClicked: terminalModel.zoom(modelData.sessionId)
                            }
                            AppButton {
                                text: "移除"
                                iconName: "trash"
                                variant: "ghost"
                                visible: modelData.status !== "running"
                                onClicked: terminalModel.removeSession(modelData.sessionId)
                            }
                        }
                    }
                }

                Text {
                    Layout.fillWidth: true
                    Layout.leftMargin: Theme.space3
                    Layout.rightMargin: Theme.space3
                    Layout.bottomMargin: Theme.space2
                    visible: terminalModel.sessions.length === 0
                    text: "还没有会话。点击右上角「新建」启动一个 AI CLI（如 codex / claude）。"
                    color: Theme.textFaint
                    font.pixelSize: Theme.fontCaption
                    wrapMode: Text.Wrap
                }
            }
        }

        // ================= 右侧：终端视图 =================
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            // 选项条：检测到 CLI 等待选择时浮出
            Rectangle {
                Layout.fillWidth: true
                visible: terminalModel.awaitingChoice && terminalModel.choices.length > 0
                implicitHeight: visible ? choiceRow.implicitHeight + Theme.space2 * 2 : 0
                color: Theme.accentSoft
                border.width: Theme.borderWidth
                border.color: Theme.accent

                RowLayout {
                    id: choiceRow
                    anchors.fill: parent
                    anchors.margins: Theme.space2
                    spacing: Theme.space2

                    Text {
                        text: "请选择："
                        color: Theme.text
                        font.pixelSize: Theme.fontBody
                        font.weight: Font.Medium
                    }

                    Repeater {
                        model: terminalModel.choices
                        delegate: AppButton {
                            required property var modelData
                            text: modelData
                            variant: "primary"
                            onClicked: terminalModel.sendChoice(index)
                        }
                    }
                }
            }

            // 输出区：只读文本流（首版用 TextArea，后续可换 VT 网格）
            ScrollView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                TextArea {
                    id: outputArea
                    text: terminalModel.screen
                    readOnly: true
                    font.family: "Consolas, Menlo, Monaco, monospace"
                    font.pixelSize: 13
                    color: Theme.text
                    background: Rectangle { color: Theme.bg }
                    textFormat: TextEdit.PlainText
                    wrapMode: TextEdit.NoWrap
                    Component.onCompleted: {
                        // 新输出时自动滚到底部
                    }
                }
            }

            // 输入栏
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: Theme.topBarHeight
                color: Theme.surface
                border.width: Theme.borderWidth
                border.color: Theme.border

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: Theme.space3
                    anchors.rightMargin: Theme.space3
                    spacing: Theme.space2

                    TextField {
                        id: inputField
                        Layout.fillWidth: true
                        placeholderText: terminalModel.activeId ? "输入并回车发送给 AI CLI …" : "请先选择或新建一个会话"
                        enabled: terminalModel.activeId !== ""
                        onAccepted: {
                            terminalModel.sendInput(text)
                            text = ""
                        }
                    }

                    AppButton {
                        text: "发送"
                        variant: "primary"
                        enabled: terminalModel.activeId !== "" && inputField.text !== ""
                        onClicked: {
                            terminalModel.sendInput(inputField.text)
                            inputField.text = ""
                        }
                    }
                }
            }
        }
    }

    // ================= 新建会话弹窗 =================
    Popup {
        id: createPopup
        modal: true
        focus: true
        anchors.centerIn: parent
        width: 540
        padding: Theme.space4
        background: Rectangle { radius: Theme.radius; color: Theme.surface; border.width: Theme.borderWidth; border.color: Theme.border }

        ColumnLayout {
            anchors.fill: parent
            spacing: Theme.space3

            Text { text: "新建 AI 终端会话"; color: Theme.text; font.pixelSize: Theme.fontTitle; font.weight: Font.DemiBold }

            // 模式切换：按项目打开 / 自定义命令
            TabBar {
                id: modeTabs
                Layout.fillWidth: true
                TabButton { text: "按项目打开" }
                TabButton { text: "自定义命令" }
            }

            StackLayout {
                Layout.fillWidth: true
                currentIndex: modeTabs.currentIndex

                // ---- 模式一：选择项目，自动导入环境与配置 ----
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: Theme.space3

                    Text {
                        Layout.fillWidth: true
                        text: "选择项目后会自动同步该项目的 Codex / Claude 配置、路由代理与运行时环境变量。"
                        color: Theme.textFaint
                        font.pixelSize: Theme.fontCaption
                        wrapMode: Text.Wrap
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: Theme.space1
                        Text { text: "项目"; color: Theme.textMuted; font.pixelSize: Theme.fontCaption }
                        AppComboBox {
                            id: projectPicker
                            Layout.fillWidth: true
                            options: {
                                var rows = []
                                var list = terminalModel.projects
                                for (var i = 0; i < list.length; i++)
                                    rows.push({ value: list[i].id, label: list[i].name })
                                return rows
                            }
                            onSelectionChanged: function (value) { newProjectId = value }
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: Theme.space1
                        Text { text: "客户端"; color: Theme.textMuted; font.pixelSize: Theme.fontCaption }
                        RowLayout {
                            spacing: Theme.space2
                            AppButton {
                                text: "Codex"
                                variant: newProjectClient === "codex" ? "primary" : "ghost"
                                onClicked: newProjectClient = "codex"
                            }
                            AppButton {
                                text: "Claude"
                                variant: newProjectClient === "claude" ? "primary" : "ghost"
                                onClicked: newProjectClient = "claude"
                            }
                        }
                    }

                    Text {
                        Layout.fillWidth: true
                        visible: terminalModel.projects.length === 0
                        text: "还没有项目，请先在「项目工作区」添加项目。"
                        color: Theme.textFaint
                        font.pixelSize: Theme.fontCaption
                        wrapMode: Text.Wrap
                    }
                }

                // ---- 模式二：自定义命令 ----
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: Theme.space3

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: Theme.space1
                        Text { text: "标题（可选）"; color: Theme.textMuted; font.pixelSize: Theme.fontCaption }
                        AppTextField {
                            Layout.fillWidth: true
                            placeholderText: "例如：codex 重构任务"
                            text: newTitle
                            onTextChanged: newTitle = text
                        }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: Theme.space1
                        Text { text: "命令"; color: Theme.textMuted; font.pixelSize: Theme.fontCaption }
                        AppTextField {
                            Layout.fillWidth: true
                            placeholderText: "codex 或 claude，可带参数"
                            text: newCommand
                            onTextChanged: newCommand = text
                        }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: Theme.space1
                        Text { text: "工作目录（可选）"; color: Theme.textMuted; font.pixelSize: Theme.fontCaption }
                        AppTextField {
                            Layout.fillWidth: true
                            placeholderText: "留空使用当前目录"
                            text: newCwd
                            onTextChanged: newCwd = text
                        }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                AppButton {
                    text: "取消"
                    variant: "ghost"
                    onClicked: createPopup.close()
                }
                AppButton {
                    text: "启动"
                    variant: "primary"
                    enabled: modeTabs.currentIndex === 0 ? newProjectId !== "" : newCommand !== ""
                    onClicked: {
                        if (modeTabs.currentIndex === 0) {
                            terminalModel.createProjectSession(newProjectId, newProjectClient)
                        } else {
                            terminalModel.createSession(newTitle, newCommand, newCwd)
                            newTitle = ""; newCommand = "codex"; newCwd = ""
                        }
                        createPopup.close()
                    }
                }
            }
        }
    }

    // ================= 放大浮窗 =================
    Window {
        id: zoomWindow
        visible: terminalModel.zoomedId !== ""
        width: 900
        height: 640
        title: "AI 终端 · 放大"
        color: Theme.bg
        onClosing: terminalModel.closeZoom()

        ColumnLayout {
            anchors.fill: parent
            spacing: 0

            // 选项条（放大视图内的独立选择）
            Rectangle {
                Layout.fillWidth: true
                visible: terminalModel.zoomedAwaiting && terminalModel.zoomedChoices.length > 0
                implicitHeight: visible ? zChoiceRow.implicitHeight + Theme.space2 * 2 : 0
                color: Theme.accentSoft
                border.width: Theme.borderWidth
                border.color: Theme.accent

                RowLayout {
                    id: zChoiceRow
                    anchors.fill: parent
                    anchors.margins: Theme.space2
                    spacing: Theme.space2
                    Text { text: "请选择："; color: Theme.text; font.pixelSize: Theme.fontBody; font.weight: Font.Medium }
                    Repeater {
                        model: terminalModel.zoomedChoices
                        delegate: AppButton {
                            required property var modelData
                            text: modelData
                            variant: "primary"
                            onClicked: terminalModel.sendZoomChoice(index)
                        }
                    }
                }
            }

            ScrollView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                TextArea {
                    text: terminalModel.zoomedScreen
                    readOnly: true
                    font.family: "Consolas, Menlo, Monaco, monospace"
                    font.pixelSize: 13
                    color: Theme.text
                    background: Rectangle { color: Theme.bg }
                    textFormat: TextEdit.PlainText
                    wrapMode: TextEdit.NoWrap
                }
            }

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: Theme.topBarHeight
                color: Theme.surface
                border.width: Theme.borderWidth
                border.color: Theme.border

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: Theme.space3
                    anchors.rightMargin: Theme.space3
                    spacing: Theme.space2

                    TextField {
                        id: zoomInput
                        Layout.fillWidth: true
                        placeholderText: "输入并回车发送给 AI CLI …"
                        onAccepted: {
                            terminalModel.sendZoomInput(text)
                            text = ""
                        }
                    }
                    AppButton {
                        text: "发送"
                        variant: "primary"
                        enabled: zoomInput.text !== ""
                        onClicked: {
                            terminalModel.sendZoomInput(zoomInput.text)
                            zoomInput.text = ""
                        }
                    }
                    AppButton {
                        text: "停止"
                        iconName: "close"
                        variant: "ghost"
                        onClicked: terminalModel.stopZoom(terminalModel.zoomedId)
                    }
                }
            }
        }
    }
}
