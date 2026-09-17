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
    // 菜单种类：confirm / numbered / list。list（如 codex resume）只能用
    // 方向键选，点按钮时界面要发 ↑↓ 而不是数字。
    property string choiceKind: "numbered"
    // 菜单当前高亮项下标；-1 表示看不出。
    property int selectedIndex: -1
    property bool inputEnabled: true
    property string placeholder: "输入并回车发送给 AI CLI …"

    // 指令候选（斜杠命令）。由上层（view model）算好，这里只负责显示与选择。
    property bool hintVisible: false
    property var hintItems: []
    property int hintSelected: -1

    signal inputSubmitted(string text)
    signal choiceSelected(int index)
    signal keySent(string key)
    // 输入框内容变化 / 需要历史翻页时回传上层。
    signal inputEdited(string text)
    signal historyRequested(bool older)
    // 候选条：移动高亮 与 确认补全 是两件事，分开表达避免语义混淆。
    signal hintMoved(int index)
    signal hintAccepted(int index)
    signal hintsClosed()

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // ---- 可选项条：检测到 CLI 等待选择时浮出 ----
        Rectangle {
            Layout.fillWidth: true
            Layout.bottomMargin: visible ? Theme.space2 : 0
            visible: root.awaitingChoice && root.choices.length > 0
            implicitHeight: visible ? choiceLayout.implicitHeight + Theme.space2 * 2 : 0
            radius: Theme.radiusSm
            color: Theme.accentSoft
            border.width: Theme.borderWidth
            border.color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.35)

            ColumnLayout {
                id: choiceLayout

                anchors.fill: parent
                anchors.margins: Theme.space2
                spacing: Theme.space1 + 2

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.space2

                    AppIcon {
                        name: "alert"
                        color: Theme.accent
                        size: 15
                    }

                    Text {
                        Layout.fillWidth: true
                        // list 类菜单（如 codex 的 resume 会话列表）不能靠发数字选中，
                        // 必须用方向键把光标移过去，所以提示文案要跟着变。
                        text: root.choiceKind === "list"
                            ? "等待选择（列表菜单：点选项会自动用 ↑↓ 移动光标后回车）"
                            : "等待你的选择（点按钮直接选定；也可用下方 ↑↓ 移动、Enter 确认）"
                        color: Theme.accent
                        font.pixelSize: Theme.fontCaption
                        wrapMode: Text.WordWrap
                    }

                    // 方向键/确认键：部分 TUI 菜单只认键盘操作
                    AppButton {
                        text: "↑"
                        variant: "secondary"
                        implicitHeight: Theme.controlHeightSm
                        onClicked: root.keySent("up")
                    }
                    AppButton {
                        text: "↓"
                        variant: "secondary"
                        implicitHeight: Theme.controlHeightSm
                        onClicked: root.keySent("down")
                    }
                    AppButton {
                        text: "Enter"
                        variant: "secondary"
                        implicitHeight: Theme.controlHeightSm
                        onClicked: root.keySent("enter")
                    }
                    AppButton {
                        text: "Esc"
                        variant: "ghost"
                        implicitHeight: Theme.controlHeightSm
                        onClicked: root.keySent("esc")
                    }
                }

                // 选项可能很多：放进可滚动的流式布局，避免溢出容器。
                Flow {
                    Layout.fillWidth: true
                    spacing: Theme.space2

                    Repeater {
                        model: root.choices

                        delegate: AppButton {
                            required property var modelData
                            required property int index

                            // 菜单当前高亮项用主色实心按钮标出，其余用描边样式：
                            // 用户一眼能看出"现在按回车会选中哪个"。
                            text: (index + 1) + ". " + modelData
                                + (index === root.selectedIndex ? "  ← 当前" : "")
                            variant: index === root.selectedIndex ? "primary" : "secondary"
                            onClicked: root.choiceSelected(index)
                        }
                    }
                }
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

        // ---- 指令候选条：输入 "/" 时浮出 ----
        Rectangle {
            id: hintBar

            Layout.fillWidth: true
            Layout.topMargin: visible ? Theme.space2 : 0
            visible: root.hintVisible && root.hintItems.length > 0
            implicitHeight: visible ? hintColumn.implicitHeight + Theme.space2 * 2 : 0
            radius: Theme.radiusSm
            color: Theme.surfaceAlt
            border.width: Theme.borderWidth
            border.color: Theme.border

            ColumnLayout {
                id: hintColumn

                anchors.fill: parent
                anchors.margins: Theme.space2
                spacing: 2

                Text {
                    Layout.fillWidth: true
                    text: "AI 指令（↑↓ 选择，Tab 补全，Esc 关闭）"
                    color: Theme.textMuted
                    font.pixelSize: Theme.fontCaption
                }

                Repeater {
                    model: root.hintItems

                    delegate: Rectangle {
                        required property var modelData
                        required property int index

                        Layout.fillWidth: true
                        implicitHeight: hintRow.implicitHeight + 6
                        radius: Theme.radiusSm
                        color: index === root.hintSelected ? Theme.accentSoft : "transparent"

                        RowLayout {
                            id: hintRow

                            anchors.fill: parent
                            anchors.leftMargin: Theme.space2
                            anchors.rightMargin: Theme.space2
                            spacing: Theme.space2

                            Text {
                                text: modelData.name
                                color: index === root.hintSelected ? Theme.accent : Theme.text
                                font.family: "Consolas, Menlo, Monaco, monospace"
                                font.pixelSize: Theme.fontCaption
                                font.weight: Font.DemiBold
                            }

                            Text {
                                Layout.fillWidth: true
                                text: modelData.description || ""
                                color: Theme.textMuted
                                font.pixelSize: Theme.fontCaption
                                elide: Text.ElideRight
                            }
                        }

                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.hintChosen(index)
                        }
                    }
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

                // 内容变化时通知上层刷新指令候选；程序化填入历史时不触发，
                // 否则翻历史会被当成"用户在编辑"而立刻退出翻页状态。
                property bool suppressEdit: false

                onTextChanged: {
                    if (!suppressEdit)
                        root.inputEdited(text)
                }

                // ↑↓ 翻历史、Tab 补全、Esc 关提示。
                // 用 Keys 处理器而不是 TextField 自带的历史逻辑，
                // 因为历史由 Python 侧按会话维护。
                Keys.onUpPressed: function (event) {
                    if (root.hintVisible) {
                        // 候选条开着时，↑↓ 用来在候选之间移动更符合直觉。
                        var count = root.hintItems.length
                        if (count > 0)
                            root.hintMoved(((root.hintSelected - 1) + count) % count)
                        event.accepted = true
                        return
                    }
                    root.historyRequested(true)
                    event.accepted = true
                }

                Keys.onDownPressed: function (event) {
                    if (root.hintVisible) {
                        var count = root.hintItems.length
                        if (count > 0)
                            root.hintMoved((root.hintSelected + 1) % count)
                        event.accepted = true
                        return
                    }
                    root.historyRequested(false)
                    event.accepted = true
                }

                Keys.onTabPressed: function (event) {
                    // Tab 确认补全；Enter 交给 TextField 正常发送。
                    if (root.hintVisible && root.hintSelected >= 0)
                        root.hintAccepted(root.hintSelected)
                    event.accepted = true
                }

                Keys.onEscapePressed: function (event) {
                    root.hintsClosed()
                    event.accepted = true
                }

                // 供上层把历史内容填回输入框（不触发 inputEdited）。
                function setTextQuietly(value) {
                    suppressEdit = true
                    text = value
                    cursorPosition = text.length
                    suppressEdit = false
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

    // 上层调用：把历史内容填进输入框并聚焦。
    function applyHistory(value) {
        inputField.setTextQuietly(value)
        inputField.forceActiveFocus()
    }

    // 输入框当前内容（开始翻历史前作为草稿保存）。
    function currentDraft() {
        return inputField.text
    }

    // 上层调用：把补全的指令填进输入框。
    function applyHintText(value) {
        inputField.setTextQuietly(value)
        inputField.forceActiveFocus()
        // 补全后重新计算候选（例如 /model 补全后不再需要提示）。
        root.inputEdited(value)
    }
}
