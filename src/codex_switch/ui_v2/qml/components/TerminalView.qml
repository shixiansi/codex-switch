import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
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

    // 风险审查的展示不在这里：主窗口由共享的 ConfirmDialog 弹窗承担，
    // 放大窗口由页面直接内嵌 ReviewBar（见 TerminalDashboard.qml）。

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
    // 附加图片：选文件 / 用剪贴板里已有的图 / 拖入的 data URL。
    signal imageFilePicked(string path)
    signal clipboardImageRequested()
    signal imageDropped(string dataUrl)

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
                            : "等待你的选择（点按钮直接选定；也可用 ↓ 下方方向键移动、Enter 确认）"
                        color: Theme.accent
                        font.pixelSize: Theme.fontCaption
                        wrapMode: Text.WordWrap
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

        // ---- 按键条：方向键 / Enter / Esc ----
        //
        // **始终可见**（只要会话存在），不跟"是否检测到菜单"挂钩。
        // 早先这几个键被放在选项面板里，于是菜单一旦没被识别出来，用户连
        // 回车和方向键都发不出去，整屏就卡死了——而 TUI 菜单恰恰只能靠按键操作。
        // 把它们独立出来，识别失败时用户仍能手动操作。
        RowLayout {
            Layout.fillWidth: true
            Layout.topMargin: visible ? Theme.space2 : 0
            visible: root.inputEnabled
            spacing: Theme.space2

            Text {
                text: "按键"
                color: Theme.textFaint
                font.pixelSize: Theme.fontCaption
            }

            // 方向键用 compact：单个箭头放进标准宽度按钮里会变成一个空荡荡的方框，
            // 四个键连排也很松散。compact 让它成为紧凑的方形键帽，更像键盘。
            //
            // 变体用 soft 而不是 secondary：这一条位于白色卡片上，而 secondary 的
            // 底色就是卡片白，只剩一圈极淡的描边——远看就是几个纯文字符号，
            // 完全不像按钮。soft 用略深一档的底色，可点性一眼可见。
            AppButton {
                text: "↑"
                variant: "soft"
                compact: true
                implicitHeight: Theme.controlHeightSm
                onClicked: root.keySent("up")

                ToolTip.visible: hovered
                ToolTip.delay: 400
                ToolTip.text: "上：菜单里向上移动 / 翻历史"
            }
            AppButton {
                text: "↓"
                variant: "soft"
                compact: true
                implicitHeight: Theme.controlHeightSm
                onClicked: root.keySent("down")

                ToolTip.visible: hovered
                ToolTip.delay: 400
                ToolTip.text: "下：菜单里向下移动 / 翻历史"
            }
            AppButton {
                text: "←"
                variant: "soft"
                compact: true
                implicitHeight: Theme.controlHeightSm
                onClicked: root.keySent("left")

                ToolTip.visible: hovered
                ToolTip.delay: 400
                ToolTip.text: "左：切换选项（部分菜单的 ←/→ change option）"
            }
            AppButton {
                text: "→"
                variant: "soft"
                compact: true
                implicitHeight: Theme.controlHeightSm
                onClicked: root.keySent("right")

                ToolTip.visible: hovered
                ToolTip.delay: 400
                ToolTip.text: "右：切换选项（部分菜单的 ←/→ change option）"
            }
            AppButton {
                text: "Enter"
                variant: "soft"
                implicitHeight: Theme.controlHeightSm
                onClicked: root.keySent("enter")

                ToolTip.visible: hovered
                ToolTip.delay: 400
                ToolTip.text: "确认当前选项"
            }
            AppButton {
                text: "Esc"
                variant: "soft"
                implicitHeight: Theme.controlHeightSm
                onClicked: root.keySent("esc")

                ToolTip.visible: hovered
                ToolTip.delay: 400
                ToolTip.text: "返回 / 取消当前菜单"
            }

            Item { Layout.fillWidth: true }
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
                            // 点击候选 = 直接补全（hintAccepted）。
                            // 曾误写成已改名的 hintChosen，导致点击报
                            // ReferenceError 而毫无反应。
                            onClicked: root.hintAccepted(index)
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
                    if (text === "")
                        return
                    // 候选条开着时发送**完整命令名**，理由见 payloadFor。
                    root.inputSubmitted(root.payloadFor(text))
                    text = ""
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
                    // Tab 只把候选填进输入框，不发送——用户可以继续加参数。
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
                text: "图片"
                iconName: "image"
                trailingIconName: "chevron-down"
                // soft：贴在输入栏的白色卡片上，secondary 的白底会与背景糊在一起。
                variant: "soft"
                enabled: root.inputEnabled
                onClicked: imageMenu.open()

                ToolTip.visible: hovered
                ToolTip.delay: 400
                ToolTip.text: "把图片附加到 AI CLI 的输入框（不会自动发送）"

                AppMenu {
                    id: imageMenu

                    // 向上弹出：这个按钮位于窗口最底部，向下弹（y = height + 4）
                    // 会直接落到窗口外面——那正是菜单溢出的原因。
                    // x 让菜单右缘与按钮右缘对齐，向左展开，避免超出右边界。
                    y: -height - Theme.space1
                    x: parent.width - width

                    AppMenuItem {
                        text: "选择图片文件…"
                        iconName: "folder"
                        onTriggered: imageDialog.open()
                    }
                    AppMenuItem {
                        text: "附加剪贴板中的图片"
                        iconName: "restore"
                        onTriggered: root.clipboardImageRequested()
                    }
                }
            }

            AppButton {
                text: "发送"
                iconName: "chevron-right"
                variant: "primary"
                enabled: root.inputEnabled && inputField.text !== ""
                onClicked: {
                    root.inputSubmitted(root.payloadFor(inputField.text))
                    inputField.text = ""
                }

                ToolTip.visible: hovered
                ToolTip.delay: 400
                ToolTip.text: "发送给 AI CLI（Enter 同效）"
            }
        }
    }

    // ---- 拖入图片：把图片文件拖到终端上即可附加 ----
    //
    // 只接受图片。QLabel/QML 的拖拽给出 data: URL，交给 Python 解码后写剪贴板。
    DropArea {
        anchors.fill: parent
        // 会话未就绪时不接受拖拽，避免"拖进去没反应"的困惑。
        enabled: root.inputEnabled

        onDropped: function (drop) {
            if (!drop.hasUrls || drop.urls.length === 0) {
                drop.acceptProposedAction()
                return
            }
            // 逐个附加；多图时 CLI 会依次显示 [Image #1] [Image #2]…
            for (var i = 0; i < drop.urls.length; i++)
                root.imageFilePicked(drop.urls[i].toString())
            drop.acceptProposedAction()
        }

        Rectangle {
            anchors.fill: parent
            visible: parent.containsDrag
            color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.08)
            border.width: Theme.borderWidth
            border.color: Theme.accent

            Text {
                anchors.centerIn: parent
                text: "松开即可附加图片"
                color: Theme.accent
                font.pixelSize: Theme.fontBody
                font.weight: Font.DemiBold
            }
        }
    }

    // 真正要发送的文本。
    //
    // 候选条开着时返回**完整命令名**而不是输入框里的前缀：
    // 输入 "/re" 时若不补全就发送，codex 会按它自己的规则匹配到第一个
    // 候选 /review——用户高亮的是 /resume，起来的却是 review 菜单。
    function payloadFor(text) {
        if (root.hintVisible && root.hintSelected >= 0
                && root.hintSelected < root.hintItems.length) {
            return root.hintItems[root.hintSelected].name
        }
        return text
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

    // 选图对话框（系统原生）。
    //
    // 用 QtQuick.Dialogs 的 FileDialog：它给出的是本地路径，可以直接交给
    // Python 校验并读图。选完**不自动发送**——图片只被附加到 CLI 的输入框，
    // 发不发、配什么文字由用户决定。
    FileDialog {
        id: imageDialog

        title: "选择要附加的图片"
        nameFilters: [ "图片 (*.png *.jpg *.jpeg *.gif *.webp *.bmp *.tif *.tiff)" ]
        onAccepted: root.imageFilePicked(selectedFile.toString())
    }

    // 上层调用：把补全的指令填进输入框。
    function applyHintText(value) {
        inputField.setTextQuietly(value)
        inputField.forceActiveFocus()
        // 补全后重新计算候选（例如 /model 补全后不再需要提示）。
        root.inputEdited(value)
    }
}
