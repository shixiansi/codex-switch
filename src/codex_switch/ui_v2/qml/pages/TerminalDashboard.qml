import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import theme
import components

// AI 终端：多开运行交互式 AI CLI，并统一回收残留进程。
Item {
    id: page

    objectName: "terminalDashboard"

    // 供截图脚本等外部调用
    function openCreateDialog() {
        createDialog.open()
    }

    // 取某个会话的展示行；找不到时返回空对象，便于 QML 安全取值。
    function rowFor(sessionId) {
        var list = terminalModel.sessions
        for (var i = 0; i < list.length; i++) {
            if (list[i].sessionId === sessionId)
                return list[i]
        }
        return ({})
    }

    function activeSession() {
        return rowFor(terminalModel.activeId)
    }

    function finishedCount() {
        var list = terminalModel.sessions
        var count = 0
        for (var i = 0; i < list.length; i++) {
            if (list[i].status !== "running")
                count++
        }
        return count
    }

    // 新建会话：按项目打开 / 自定义命令
    property string newProjectId: ""
    // 是否显示带时间戳的时间线面板
    property bool showTimeline: false
    property string newProjectClient: "codex"
    property string newTitle: ""
    property string newCommand: "codex"
    property string newCwd: ""

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.space5
        spacing: Theme.space4

        // PTY 环境不可用时直接说明原因，避免"界面一片空白不知从何查起"。
        Rectangle {
            Layout.fillWidth: true
            visible: terminalModel.backendIssue !== ""
            implicitHeight: issueText.implicitHeight + Theme.space3 * 2
            radius: Theme.radiusSm
            color: Theme.dangerSoft
            border.width: Theme.borderWidth
            border.color: Qt.rgba(Theme.danger.r, Theme.danger.g, Theme.danger.b, 0.35)

            RowLayout {
                anchors.fill: parent
                anchors.margins: Theme.space3
                spacing: Theme.space2

                AppIcon {
                    Layout.alignment: Qt.AlignTop
                    name: "warning"
                    color: Theme.danger
                    size: 16
                }

                Text {
                    id: issueText
                    Layout.fillWidth: true
                    text: "终端环境不可用：" + terminalModel.backendIssue
                    color: Theme.danger
                    font.pixelSize: Theme.fontCaption
                    wrapMode: Text.WordWrap
                }

                AppButton {
                    text: "打开日志"
                    iconName: "log"
                    variant: "ghost"
                    onClicked: app.openLocalPath(terminalModel.logPath)
                }
            }
        }

        SectionHeader {
            title: "AI 终端"
            description: "在应用内运行 codex / claude 等交互式 AI CLI，支持多开会话、放大查看，并在结束时整树回收残留进程。"

            AppButton {
                text: "打开日志"
                iconName: "log"
                onClicked: app.openLocalPath(terminalModel.logPath)

                ToolTip.visible: hovered
                ToolTip.delay: 400
                ToolTip.text: "查看终端日志（启动命令、输出、退出与回收记录）"
            }
            AppButton {
                text: terminalModel.autoAnswer ? "自动选择：开" : "自动选择：关"
                iconName: terminalModel.autoAnswer ? "check" : "close"
                variant: terminalModel.autoAnswer ? "primary" : "ghost"
                onClicked: terminalModel.setAutoAnswer(!terminalModel.autoAnswer)

                ToolTip.visible: hovered
                ToolTip.delay: 400
                ToolTip.text: "开启后，检测到选择菜单会自动选第一项（如 codex 的信任目录确认）"
            }
            AppButton {
                text: "清理残留"
                iconName: "refresh"
                enabled: terminalModel.runningCount === 0 || terminalModel.sessions.length > 0
                onClicked: terminalModel.cleanupOrphans()

                ToolTip.visible: hovered
                ToolTip.delay: 400
                ToolTip.text: "回收已结束会话遗留的子进程"
            }
            AppButton {
                text: "新建会话"
                iconName: "plus"
                variant: "primary"
                onClicked: createDialog.open()
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: Theme.space4

            // ================= 左：会话总览 =================
            Rectangle {
                Layout.preferredWidth: 320
                Layout.fillHeight: true
                radius: Theme.radius
                color: Theme.surface
                border.width: Theme.borderWidth
                border.color: Theme.border

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: Theme.space3
                    spacing: Theme.space2

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.space2

                        Text {
                            Layout.fillWidth: true
                            text: "会话 (" + terminalModel.sessions.length + ")"
                            color: Theme.text
                            font.pixelSize: Theme.fontSubtitle
                            font.weight: Font.DemiBold
                        }

                        StatusBadge {
                            text: terminalModel.runningCount + " 运行中"
                            tone: terminalModel.runningCount > 0 ? "accent" : "unknown"
                            showDot: terminalModel.runningCount > 0
                            visible: terminalModel.sessions.length > 0
                        }

                        AppButton {
                            text: "清除已结束"
                            iconName: "close"
                            variant: "ghost"
                            implicitHeight: Theme.controlHeightSm
                            visible: page.finishedCount() > 0
                            onClicked: terminalModel.clearFinished()
                        }
                    }

                    EmptyState {
                        Layout.fillWidth: true
                        visible: terminalModel.sessions.length === 0
                        iconName: "terminal"
                        title: "还没有会话"
                        description: "点击右上角「新建会话」，按项目打开或运行自定义命令。"
                        actionText: "新建会话"
                        onActionTriggered: createDialog.open()
                    }

                    ListView {
                        id: sessionList

                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        visible: terminalModel.sessions.length > 0
                        model: terminalModel.sessions
                        spacing: Theme.space1
                        boundsBehavior: Flickable.StopAtBounds
                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                        delegate: ListRow {
                            id: row

                            required property var modelData

                            width: sessionList.width
                            iconName: "terminal"
                            title: modelData.title
                            subtitle: modelData.lastLine !== ""
                                ? modelData.lastLine : modelData.cwd
                            badgeText: modelData.statusLabel
                            badgeTone: modelData.status === "running" ? "accent"
                                : modelData.status === "completed" ? "success"
                                : modelData.status === "failed" ? "danger" : "unknown"
                            // 运行时长作为尾部提示，便于同时多开时对照进度。
                            meta: modelData.elapsedLabel || ""
                            selected: terminalModel.activeId === modelData.sessionId
                            onClicked: terminalModel.focus(modelData.sessionId)
                        }
                    }
                }
            }

            // ================= 右：终端视图 =================
            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: Theme.radius
                color: Theme.surface
                border.width: Theme.borderWidth
                border.color: Theme.border

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: Theme.space3
                    spacing: Theme.space3

                    // ---- 头部：标题 + 路径 + 状态 ----
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.space2
                        visible: terminalModel.activeId !== ""

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 1

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: Theme.space2

                                Text {
                                    Layout.fillWidth: true
                                    text: page.activeSession().title || ""
                                    color: Theme.text
                                    font.pixelSize: Theme.fontTitle
                                    font.weight: Font.DemiBold
                                    elide: Text.ElideRight
                                }

                                // 运行时长：随轮询实时更新
                                StatusBadge {
                                    Layout.alignment: Qt.AlignVCenter
                                    text: (page.activeSession().status === "running" ? "已运行 " : "耗时 ")
                                        + (page.activeSession().elapsedLabel || "0s")
                                    tone: page.activeSession().status === "running" ? "accent" : "unknown"
                                    showDot: page.activeSession().status === "running"
                                }
                            }

                            Text {
                                Layout.fillWidth: true
                                text: page.activeSession().cwd || ""
                                color: Theme.textFaint
                                font.pixelSize: Theme.fontCaption
                                elide: Text.ElideMiddle
                            }
                        }

                        AppButton {
                            text: page.showTimeline ? "隐藏时间线" : "时间线"
                            iconName: "log"
                            variant: page.showTimeline ? "primary" : "ghost"
                            visible: page.activeSession().status !== ""
                            onClicked: page.showTimeline = !page.showTimeline

                            ToolTip.visible: hovered
                            ToolTip.delay: 400
                            ToolTip.text: "按时间顺序查看带时间戳的输出段落"
                        }
                        AppButton {
                            text: "放大"
                            iconName: "search"
                            variant: "ghost"
                            visible: page.activeSession().status === "running"
                            onClicked: terminalModel.zoom(terminalModel.activeId)
                        }
                        // 运行中可"停止"；已结束则只提供"清除"，避免按钮点了没反应。
                        AppButton {
                            text: "停止"
                            iconName: "close"
                            variant: "danger"
                            visible: page.activeSession().status === "running"
                            onClicked: terminalModel.stopSession(terminalModel.activeId)
                        }
                        AppButton {
                            text: "清除"
                            iconName: "close"
                            variant: "secondary"
                            visible: page.activeSession().status !== "running"
                            onClicked: terminalModel.removeSession(terminalModel.activeId)
                        }
                    }

                    EmptyState {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        visible: terminalModel.activeId === ""
                        iconName: "terminal"
                        title: "未选择会话"
                        description: "在左侧选择一个会话查看实时输出，或新建一个会话。"
                    }

                    TerminalView {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        visible: terminalModel.activeId !== "" && !page.showTimeline
                        screenText: terminalModel.screen
                        awaitingChoice: terminalModel.awaitingChoice
                        choices: terminalModel.choices
                        inputEnabled: terminalModel.activeId !== ""
                        onInputSubmitted: function (text) { terminalModel.sendInput(text) }
                        onChoiceSelected: function (index) { terminalModel.sendChoice(index) }
                        onKeySent: function (key) { terminalModel.sendKey(key) }
                    }

                    // ---- 时间线：带时间戳的输出段落 ----
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        visible: terminalModel.activeId !== "" && page.showTimeline
                        radius: Theme.radiusSm
                        color: Theme.codeBg
                        border.width: Theme.borderWidth
                        border.color: Theme.border

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: Theme.space2
                            spacing: Theme.space2

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: Theme.space2

                                AppIcon { name: "log"; color: Theme.accent; size: 15 }

                                Text {
                                    Layout.fillWidth: true
                                    text: "时间线　·　每段输出按发生时间排列"
                                    color: Theme.accent
                                    font.pixelSize: Theme.fontCaption
                                    font.weight: Font.Medium
                                }

                                AppButton {
                                    text: "回到终端"
                                    variant: "ghost"
                                    implicitHeight: Theme.controlHeightSm
                                    onClicked: page.showTimeline = false
                                }
                            }

                            Flickable {
                                id: timelineFlick

                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                contentWidth: width
                                contentHeight: timelineText.implicitHeight
                                clip: true
                                boundsBehavior: Flickable.StopAtBounds
                                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                                property bool pinnedToBottom: true
                                onContentYChanged: pinnedToBottom = contentY >= contentHeight - height - 2
                                onContentHeightChanged: {
                                    if (pinnedToBottom)
                                        contentY = Math.max(0, contentHeight - height)
                                }

                                Text {
                                    id: timelineText

                                    width: parent.width
                                    text: terminalModel.activeTimeline !== ""
                                        ? terminalModel.activeTimeline
                                        : "（暂无输出）"
                                    color: terminalModel.activeTimeline !== "" ? Theme.text : Theme.textFaint
                                    font.family: "Consolas, Menlo, Monaco, monospace"
                                    font.pixelSize: 12
                                    wrapMode: Text.WrapAnywhere
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    // ================= 新建会话对话框 =================
    Popup {
        id: createDialog

        anchors.centerIn: parent
        width: Math.min(560, page.width - Theme.space6 * 2)
        modal: true
        focus: true
        padding: 0
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        background: Rectangle {
            radius: Theme.radius
            color: Theme.surface
            border.width: Theme.borderWidth
            border.color: Theme.border
        }

        contentItem: ColumnLayout {
            spacing: 0

            // ---- 头部 ----
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: headerRow.implicitHeight + Theme.space4 * 2
                color: "transparent"

                RowLayout {
                    id: headerRow

                    anchors.fill: parent
                    anchors.leftMargin: Theme.space4
                    anchors.rightMargin: Theme.space4
                    spacing: Theme.space2

                    Rectangle {
                        width: 30
                        height: 30
                        radius: Theme.radiusSm
                        color: Theme.accentSoft

                        AppIcon {
                            anchors.centerIn: parent
                            name: "terminal"
                            color: Theme.accent
                            size: 16
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 1

                        Text {
                            text: "新建 AI 终端会话"
                            color: Theme.text
                            font.pixelSize: Theme.fontTitle
                            font.weight: Font.DemiBold
                        }

                        Text {
                            text: "在应用内运行交互式 AI CLI"
                            color: Theme.textMuted
                            font.pixelSize: Theme.fontCaption
                        }
                    }

                    AppButton {
                        text: "关闭"
                        iconName: "close"
                        variant: "ghost"
                        onClicked: createDialog.close()
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 1
                color: Theme.border
            }

            // ---- 主体 ----
            ColumnLayout {
                Layout.fillWidth: true
                Layout.margins: Theme.space4
                spacing: Theme.space3

                // 模式切换：分段控件（避免默认 TabBar 的粗黑样式）
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: Theme.controlHeight
                    radius: Theme.radiusSm
                    color: Theme.surfaceAlt
                    border.width: Theme.borderWidth
                    border.color: Theme.border

                    RowLayout {
                        anchors.fill: parent
                        anchors.margins: 2
                        spacing: 2

                        Repeater {
                            model: [ "按项目打开", "自定义命令" ]

                            delegate: Rectangle {
                                required property var modelData
                                required property int index

                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                radius: Theme.radiusSm - 2
                                color: modeTabs.current === index ? Theme.surface : "transparent"
                                border.width: modeTabs.current === index ? Theme.borderWidth : 0
                                border.color: Theme.border

                                Text {
                                    anchors.centerIn: parent
                                    text: modelData
                                    color: modeTabs.current === index ? Theme.accent : Theme.textMuted
                                    font.pixelSize: Theme.fontBody
                                    font.weight: modeTabs.current === index ? Font.DemiBold : Font.Normal
                                }

                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: modeTabs.current = index
                                }
                            }
                        }
                    }
                }

                QtObject {
                    id: modeTabs
                    property int current: 0
                }

                // ---- 模式一：按项目打开 ----
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: Theme.space3
                    visible: modeTabs.current === 0

                    Text {
                        Layout.fillWidth: true
                        text: "选择项目后会自动同步该项目的 Codex / Claude 配置、路由代理与运行时环境变量，并以项目目录作为工作目录启动。"
                        color: Theme.textMuted
                        font.pixelSize: Theme.fontCaption
                        wrapMode: Text.WordWrap
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: Theme.space1

                        Text {
                            text: "项目"
                            color: Theme.textMuted
                            font.pixelSize: Theme.fontCaption
                        }

                        AppComboBox {
                            Layout.fillWidth: true
                            options: {
                                var rows = []
                                var list = terminalModel.projects
                                for (var i = 0; i < list.length; i++)
                                    rows.push({ value: list[i].id, label: list[i].name })
                                return rows
                            }
                            onSelectionChanged: function (value) { page.newProjectId = value }
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: Theme.space1

                        Text {
                            text: "客户端"
                            color: Theme.textMuted
                            font.pixelSize: Theme.fontCaption
                        }

                        RowLayout {
                            spacing: Theme.space2

                            AppButton {
                                text: "Codex"
                                variant: page.newProjectClient === "codex" ? "primary" : "secondary"
                                onClicked: page.newProjectClient = "codex"
                            }
                            AppButton {
                                text: "Claude"
                                variant: page.newProjectClient === "claude" ? "primary" : "secondary"
                                onClicked: page.newProjectClient = "claude"
                            }
                            Item { Layout.fillWidth: true }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: noProjectText.implicitHeight + Theme.space2 * 2
                        radius: Theme.radiusSm
                        color: Theme.warningSoft
                        visible: terminalModel.projects.length === 0

                        Text {
                            id: noProjectText
                            anchors.fill: parent
                            anchors.margins: Theme.space2
                            text: "还没有项目，请先在「项目工作区」添加项目。"
                            color: Theme.warning
                            font.pixelSize: Theme.fontCaption
                            wrapMode: Text.WordWrap
                        }
                    }
                }

                // ---- 模式二：自定义命令 ----
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: Theme.space3
                    visible: modeTabs.current === 1

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: Theme.space1

                        Text { text: "标题（可选）"; color: Theme.textMuted; font.pixelSize: Theme.fontCaption }

                        AppTextField {
                            Layout.fillWidth: true
                            placeholderText: "例如：codex 重构任务"
                            text: page.newTitle
                            onTextChanged: page.newTitle = text
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: Theme.space1

                        Text { text: "命令"; color: Theme.textMuted; font.pixelSize: Theme.fontCaption }

                        AppTextField {
                            Layout.fillWidth: true
                            placeholderText: "codex 或 claude，可带参数"
                            text: page.newCommand
                            onTextChanged: page.newCommand = text
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: Theme.space1

                        Text { text: "工作目录（可选）"; color: Theme.textMuted; font.pixelSize: Theme.fontCaption }

                        AppTextField {
                            Layout.fillWidth: true
                            placeholderText: "留空使用当前目录"
                            text: page.newCwd
                            onTextChanged: page.newCwd = text
                        }
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 1
                color: Theme.border
            }

            // ---- 底部操作 ----
            RowLayout {
                Layout.fillWidth: true
                Layout.margins: Theme.space4
                spacing: Theme.space2

                Item { Layout.fillWidth: true }

                AppButton {
                    text: "取消"
                    variant: "ghost"
                    onClicked: createDialog.close()
                }

                AppButton {
                    text: "启动"
                    iconName: "chevron-right"
                    variant: "primary"
                    enabled: modeTabs.current === 0
                        ? page.newProjectId !== ""
                        : page.newCommand !== ""
                    onClicked: {
                        if (modeTabs.current === 0)
                            terminalModel.createProjectSession(page.newProjectId, page.newProjectClient)
                        else
                            terminalModel.createSession(page.newTitle, page.newCommand, page.newCwd)
                        page.newTitle = ""
                        page.newCommand = "codex"
                        page.newCwd = ""
                        createDialog.close()
                    }
                }
            }
        }
    }

    // ================= 放大浮窗 =================
    Window {
        id: zoomWindow

        visible: terminalModel.zoomedId !== ""
        width: 960
        height: 680
        title: "AI 终端 · 放大"
        color: Theme.bg
        onClosing: terminalModel.closeZoom()

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: Theme.space4
            spacing: Theme.space3

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.space2

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 1

                    Text {
                        Layout.fillWidth: true
                        text: {
                            var list = terminalModel.sessions
                            for (var i = 0; i < list.length; i++) {
                                if (list[i].sessionId === terminalModel.zoomedId)
                                    return list[i].title
                            }
                            return "AI 终端"
                        }
                        color: Theme.text
                        font.pixelSize: Theme.fontTitle
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                    }

                    Text {
                        Layout.fillWidth: true
                        text: {
                            var list = terminalModel.sessions
                            for (var i = 0; i < list.length; i++) {
                                if (list[i].sessionId === terminalModel.zoomedId)
                                    return list[i].cwd
                            }
                            return ""
                        }
                        color: Theme.textFaint
                        font.pixelSize: Theme.fontCaption
                        elide: Text.ElideMiddle
                    }
                }

                AppButton {
                    text: "停止"
                    iconName: "close"
                    variant: "danger"
                    onClicked: terminalModel.stopZoom(terminalModel.zoomedId)
                }
            }

            TerminalView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                screenText: terminalModel.zoomedScreen
                awaitingChoice: terminalModel.zoomedAwaiting
                choices: terminalModel.zoomedChoices
                inputEnabled: terminalModel.zoomedId !== ""
                onInputSubmitted: function (text) { terminalModel.sendZoomInput(text) }
                onChoiceSelected: function (index) { terminalModel.sendZoomChoice(index) }
                onKeySent: function (key) { terminalModel.sendZoomKey(key) }
            }
        }
    }
}
