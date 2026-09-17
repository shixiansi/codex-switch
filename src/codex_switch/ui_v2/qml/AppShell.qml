import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import theme
import components
import "pages"

ApplicationWindow {
    id: shell

    // Larger than 1180x780 baseline but fully usable down to the minimum.
    width: 1360
    height: 880
    minimumWidth: 1080
    minimumHeight: 700
    visible: true
    title: app.appTitle + " · " + app.version
    color: Theme.bg

    // Snapshot-free accessors: view models already hold display state.
    readonly property var navSections: [
        { key: "dashboard", label: "首页", icon: "grid", hint: "总览" },
        { key: "profiles", label: "配置中心", icon: "profile", hint: "配置 / 模型 / 号池" },
        { key: "projects", label: "项目工作区", icon: "folder", hint: "项目 / 模板 / MCP / Skills" },
        { key: "network", label: "网络与监控", icon: "route", hint: "代理 / 统计 / 日志" },
        { key: "scripts", label: "脚本中心", icon: "terminal", hint: "添加 / 运行 / 修改脚本" },
        { key: "terminal", label: "AI 终端", icon: "terminal", hint: "多开 AI CLI / 零残留" },
        { key: "plugins", label: "插件中心", icon: "cube", hint: "安装 / 启停 / 权限" },
        { key: "system", label: "系统", icon: "settings", hint: "模板 / 更新 / 设置" }
    ]

    Shortcut {
        sequence: "Ctrl+R"
        onActivated: app.refreshAll()
    }
    Shortcut {
        sequence: "Ctrl+K"
        onActivated: commandPalette.open()
    }
    Shortcut {
        sequence: "Ctrl+D"
        onActivated: app.themeController.toggle()
    }
    Shortcut {
        sequence: "Ctrl+1"
        onActivated: app.navigateTo("dashboard")
    }
    Shortcut {
        sequence: "Ctrl+2"
        onActivated: app.navigateTo("profiles")
    }
    Shortcut {
        sequence: "Ctrl+3"
        onActivated: app.navigateTo("projects")
    }
    Shortcut {
        sequence: "Ctrl+4"
        onActivated: app.navigateTo("network")
    }
    Shortcut {
        sequence: "Ctrl+6"
        onActivated: app.navigateTo("scripts")
    }
    Shortcut {
        sequence: "Ctrl+5"
        onActivated: app.navigateTo("system")
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // ================= top context bar =================
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: Theme.topBarHeight
            color: Theme.surface
            border.width: Theme.borderWidth
            border.color: Theme.border

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Theme.space4
                anchors.rightMargin: Theme.space4
                spacing: Theme.space4

                Text {
                    text: app.currentSectionTitle
                    color: Theme.text
                    font.pixelSize: Theme.fontTitle
                    font.weight: Font.DemiBold
                }

                Rectangle {
                    Layout.preferredWidth: 1
                    Layout.preferredHeight: 22
                    color: Theme.border
                }

                Repeater {
                    model: app.contextInfo

                    delegate: RowLayout {
                        required property var modelData

                        spacing: Theme.space1 + 2

                        Text {
                            text: modelData.label
                            color: Theme.textFaint
                            font.pixelSize: Theme.fontCaption
                            Layout.alignment: Qt.AlignVCenter
                        }

                        Text {
                            text: modelData.value
                            color: Theme.text
                            font.pixelSize: Theme.fontCaption
                            font.weight: Font.Medium
                            elide: Text.ElideRight
                            Layout.maximumWidth: 220
                            Layout.alignment: Qt.AlignVCenter
                        }
                    }
                }

                Item { Layout.fillWidth: true }

                // Inline busy indicator
                RowLayout {
                    spacing: Theme.space1 + 2
                    visible: app.busy

                    Rectangle {
                        width: 8
                        height: 8
                        radius: 4
                        color: Theme.accent

                        SequentialAnimation on opacity {
                            running: app.busy
                            loops: Animation.Infinite
                            NumberAnimation { to: 0.25; duration: 600 }
                            NumberAnimation { to: 1.0; duration: 600 }
                        }
                    }

                    Text {
                        text: app.activeTask !== "" ? app.activeTask : "处理中"
                        color: Theme.textMuted
                        font.pixelSize: Theme.fontCaption
                    }
                }

                AppButton {
                    text: "命令"
                    iconName: "search"
                    variant: "ghost"
                    onClicked: commandPalette.open()
                }

                AppButton {
                    text: app.themeController.label
                    iconName: "settings"
                    variant: "ghost"
                    onClicked: app.themeController.toggle()
                }
            }
        }

        BusyBar {
            Layout.fillWidth: true
            running: app.busy
        }

        // ================= body: nav + content =================
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            // ---- left navigation ----
            Rectangle {
                Layout.preferredWidth: Theme.navWidth
                Layout.fillHeight: true
                color: Theme.surface
                border.width: Theme.borderWidth
                border.color: Theme.border

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: Theme.space2
                    spacing: Theme.space1

                    // brand
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.margins: Theme.space2
                        spacing: Theme.space2

                        Rectangle {
                            width: 30
                            height: 30
                            radius: Theme.radiusSm
                            color: Theme.accent

                            Text {
                                anchors.centerIn: parent
                                text: "CS"
                                color: Theme.accentText
                                font.pixelSize: Theme.fontSubtitle
                                font.weight: Font.Bold
                            }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 0

                            Text {
                                text: app.appTitle
                                color: Theme.text
                                font.pixelSize: Theme.fontBody
                                font.weight: Font.DemiBold
                            }

                            Text {
                                text: "v" + app.version
                                color: Theme.textFaint
                                font.pixelSize: Theme.fontCaption
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 1
                        Layout.margins: Theme.space1
                        color: Theme.border
                    }

                    Repeater {
                        model: shell.navSections

                        delegate: Rectangle {
                            id: navItem

                            required property var modelData

                            readonly property bool active: app.currentSection === navItem.modelData.key

                            Layout.fillWidth: true
                            implicitHeight: 42
                            radius: Theme.radiusSm
                            // Opacity-animated layer: animating `color` from
                            // "transparent" interpolates from black and flashes.
                            color: "transparent"

                            Rectangle {
                                anchors.fill: parent
                                radius: parent.radius
                                color: navItem.active ? Theme.accentSoft : Theme.surfaceHover
                                opacity: navItem.active || navHover.containsMouse ? 1 : 0

                                Behavior on opacity {
                                    NumberAnimation {
                                        duration: Theme.durationFast
                                        easing.type: Easing.OutCubic
                                    }
                                }
                            }

                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: Theme.space2
                                anchors.rightMargin: Theme.space2
                                spacing: Theme.space2

                                Rectangle {
                                    Layout.preferredWidth: 3
                                    Layout.preferredHeight: 18
                                    radius: 2
                                    color: navItem.active ? Theme.accent : "transparent"
                                }

                                AppIcon {
                                    name: navItem.modelData.icon
                                    color: navItem.active ? Theme.accent : Theme.textMuted
                                    size: 17
                                }

                                Text {
                                    Layout.fillWidth: true
                                    text: navItem.modelData.label
                                    color: navItem.active ? Theme.accent : Theme.text
                                    font.pixelSize: Theme.fontBody
                                    font.weight: navItem.active ? Font.DemiBold : Font.Normal
                                    elide: Text.ElideRight
                                }

                                // 运行中的 AI 终端会话数红点徽标
                                Rectangle {
                                    width: 18
                                    height: 18
                                    radius: 9
                                    color: Theme.danger
                                    visible: navItem.modelData.key === "terminal" && terminalModel.runningCount > 0
                                    Text {
                                        anchors.centerIn: parent
                                        text: terminalModel.runningCount
                                        color: Theme.accentText
                                        font.pixelSize: 11
                                        font.weight: Font.Bold
                                    }
                                }
                            }

                            MouseArea {
                                id: navHover
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: app.navigateTo(navItem.modelData.key)
                            }
                        }
                    }

                    Item { Layout.fillHeight: true }

                    // nav footer: proxy + theme quick state
                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: navFooter.implicitHeight + Theme.space2 * 2
                        radius: Theme.radiusSm
                        color: Theme.surfaceAlt

                        ColumnLayout {
                            id: navFooter
                            anchors.fill: parent
                            anchors.margins: Theme.space2
                            spacing: Theme.space1

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: Theme.space1 + 2

                                Rectangle {
                                    width: 7
                                    height: 7
                                    radius: 4
                                    color: proxyModel.status.running ? Theme.success : Theme.unknown
                                }

                                Text {
                                    Layout.fillWidth: true
                                    text: proxyModel.status.running ? "代理运行中" : "代理未启动"
                                    color: Theme.textMuted
                                    font.pixelSize: Theme.fontCaption
                                    elide: Text.ElideRight
                                }
                            }

                            Text {
                                Layout.fillWidth: true
                                text: proxyModel.status.baseUrl
                                color: Theme.textFaint
                                font.pixelSize: Theme.fontCaption
                                elide: Text.ElideRight
                            }
                        }
                    }
                }
            }

            // ---- content area ----
            StackLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                currentIndex: {
                    var keys = ["dashboard", "profiles", "projects", "network", "scripts", "terminal", "plugins", "system"]
                    var index = keys.indexOf(app.currentSection)
                    return index === -1 ? 0 : index
                }

                DashboardPage {}
                ProfilesPage {}
                ProjectsPage {}
                NetworkPage {}
                ScriptsPage {}
                TerminalDashboard {}
                PluginsPage {}
                SystemPage {}
            }
        }

        // ================= bottom status bar =================
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: Theme.statusBarHeight
            color: Theme.surface
            border.width: Theme.borderWidth
            border.color: Theme.border

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Theme.space3
                anchors.rightMargin: Theme.space3
                spacing: Theme.space3

                Rectangle {
                    width: 7
                    height: 7
                    radius: 4
                    color: app.busy ? Theme.accent : Theme.success

                    SequentialAnimation on opacity {
                        running: app.busy
                        loops: Animation.Infinite
                        NumberAnimation { to: 0.3; duration: 700 }
                        NumberAnimation { to: 1.0; duration: 700 }
                    }
                }

                Text {
                    Layout.fillWidth: true
                    text: app.statusText
                    color: Theme.textMuted
                    font.pixelSize: Theme.fontCaption
                    elide: Text.ElideRight
                }

                Text {
                    text: dashboardModel.summary.profileCount + " 配置 · "
                        + dashboardModel.summary.projectCount + " 项目"
                    color: Theme.textFaint
                    font.pixelSize: Theme.fontCaption
                }

                Text {
                    text: app.themeController.label + "主题"
                    color: Theme.textFaint
                    font.pixelSize: Theme.fontCaption
                }
            }
        }
    }

    // ================= global overlay: drawers =================
    Loader {
        anchors.fill: parent
        active: app.drawerOpen
        sourceComponent: drawerComponent
    }

    Component {
        id: drawerComponent

        AppDrawer {
            open: true
            title: app.drawer === "profile-form" ? profilesModel.formTitle
                : app.drawer === "project-form" ? projectsModel.formTitle
                : app.drawer === "script-form" ? scriptsModel.formTitle
                : app.drawer === "pool-group-form" || app.drawer === "pool-channel-form"
                  || app.drawer === "mcp-form" || app.drawer === "skill-group-form"
                  || app.drawer === "skill-form" || app.drawer === "skill-repo-form"
                  ? toolsModel.formTitle
                : "详情"
            subtitle: app.drawer

            onClosed: app.closeDrawer()

            Loader {
                Layout.fillWidth: true
                sourceComponent: {
                    if (app.drawer === "profile-form")
                        return profileFormComponent
                    if (app.drawer === "project-form")
                        return projectFormComponent
                    if (app.drawer === "pool-group-form")
                        return poolGroupFormComponent
                    if (app.drawer === "pool-channel-form")
                        return poolChannelFormComponent
                    if (app.drawer === "mcp-form")
                        return mcpFormComponent
                    if (app.drawer === "skill-group-form")
                        return skillGroupFormComponent
                    if (app.drawer === "skill-form")
                        return skillFormComponent
                    if (app.drawer === "skill-repo-form")
                        return skillRepoFormComponent
                    if (app.drawer === "script-form")
                        return scriptFormComponent
                    return null
                }
            }
        }
    }

    Component {
        id: profileFormComponent
        FormRenderer {
            Layout.fillWidth: true
            fields: profilesModel.formFields
            onSubmitted: function (payload) { profilesModel.submitForm(payload) }
            onCancelled: app.closeDrawer()
        }
    }

    Component {
        id: projectFormComponent
        FormRenderer {
            Layout.fillWidth: true
            fields: projectsModel.formFields
            onSubmitted: function (payload) { projectsModel.submitForm(payload) }
            onCancelled: app.closeDrawer()
        }
    }

    Component {
        id: poolGroupFormComponent
        FormRenderer {
            Layout.fillWidth: true
            fields: toolsModel.formFields
            onSubmitted: function (payload) { toolsModel.submitPoolGroupForm(payload) }
            onCancelled: app.closeDrawer()
        }
    }

    Component {
        id: poolChannelFormComponent
        FormRenderer {
            Layout.fillWidth: true
            fields: toolsModel.formFields
            onSubmitted: function (payload) { toolsModel.submitPoolChannelForm(payload) }
            onCancelled: app.closeDrawer()
        }
    }

    Component {
        id: mcpFormComponent
        FormRenderer {
            Layout.fillWidth: true
            fields: toolsModel.formFields
            onSubmitted: function (payload) { toolsModel.submitMcpForm(payload) }
            onCancelled: app.closeDrawer()
        }
    }

    Component {
        id: skillGroupFormComponent
        FormRenderer {
            Layout.fillWidth: true
            fields: toolsModel.formFields
            onSubmitted: function (payload) { toolsModel.submitSkillGroupForm(payload) }
            onCancelled: app.closeDrawer()
        }
    }

    Component {
        id: skillFormComponent
        FormRenderer {
            Layout.fillWidth: true
            fields: toolsModel.formFields
            onSubmitted: function (payload) { toolsModel.submitSkillForm(payload) }
            onCancelled: app.closeDrawer()
        }
    }

    Component {
        id: skillRepoFormComponent
        FormRenderer {
            Layout.fillWidth: true
            fields: toolsModel.formFields
            onSubmitted: function (payload) { toolsModel.submitSkillRepoForm(payload) }
            onCancelled: app.closeDrawer()
        }
    }

    Component {
        id: scriptFormComponent
        FormRenderer {
            Layout.fillWidth: true
            fields: scriptsModel.form
            onSubmitted: function (payload) { scriptsModel.submitForm(payload) }
            onCancelled: app.closeDrawer()
        }
    }

    // ================= command palette =================
    Popup {
        id: commandPalette

        anchors.centerIn: parent
        width: Math.min(560, shell.width - Theme.space6 * 2)
        height: Math.min(420, paletteColumn.implicitHeight + Theme.space4 * 2)
        modal: true
        focus: true
        padding: Theme.space3

        background: Rectangle {
            radius: Theme.radius
            color: Theme.surface
            border.width: Theme.borderWidth
            border.color: Theme.border
        }

        ColumnLayout {
            id: paletteColumn
            anchors.fill: parent
            spacing: Theme.space2

            Text {
                Layout.fillWidth: true
                text: "命令面板"
                color: Theme.text
                font.pixelSize: Theme.fontTitle
                font.weight: Font.DemiBold
            }

            SearchField {
                id: paletteSearch
                Layout.fillWidth: true
                placeholderText: "输入以筛选命令 …"
            }

            ListView {
                id: paletteList
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                model: shell.filteredCommands(paletteSearch.text)
                boundsBehavior: Flickable.StopAtBounds

                delegate: Rectangle {
                    id: commandRow

                    required property var modelData

                    width: paletteList.width
                    height: 38
                    radius: Theme.radiusSm
                    color: commandHover.containsMouse ? Theme.surfaceHover : "transparent"

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: Theme.space2
                        anchors.rightMargin: Theme.space2
                        spacing: Theme.space2

                        AppIcon {
                            name: commandRow.modelData.icon
                            color: Theme.textMuted
                            size: 15
                        }

                        Text {
                            Layout.fillWidth: true
                            text: commandRow.modelData.label
                            color: Theme.text
                            font.pixelSize: Theme.fontBody
                            elide: Text.ElideRight
                        }

                        Text {
                            text: commandRow.modelData.hint
                            color: Theme.textFaint
                            font.pixelSize: Theme.fontCaption
                        }
                    }

                    MouseArea {
                        id: commandHover
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            commandPalette.close()
                            app.navigateTo(commandRow.modelData.section)
                        }
                    }
                }
            }
        }
    }

    function commandList() {
        return [
            { label: "刷新全部状态", hint: "Ctrl+R", icon: "refresh", section: "dashboard" },
            { label: "首页总览", hint: "Ctrl+1", icon: "grid", section: "dashboard" },
            { label: "配置中心 · 配置库", hint: "Ctrl+2", icon: "profile", section: "profiles" },
            { label: "项目工作区", hint: "Ctrl+3", icon: "folder", section: "projects" },
            { label: "网络与监控", hint: "Ctrl+4", icon: "route", section: "network" },
            { label: "脚本中心", hint: "Ctrl+6", icon: "terminal", section: "scripts" },
            { label: "系统设置", hint: "Ctrl+5", icon: "settings", section: "system" },
            { label: "切换浅色 / 深色主题", hint: "Ctrl+D", icon: "settings", section: "system" }
        ]
    }

    function filteredCommands(query) {
        var needle = String(query === undefined || query === null ? "" : query).toLowerCase()
        var all = shell.commandList()
        if (needle === "")
            return all
        var result = []
        for (var i = 0; i < all.length; i++) {
            if (all[i].label.toLowerCase().indexOf(needle) !== -1)
                result.push(all[i])
        }
        return result
    }

    // ================= toasts =================
    ToastHost {
        id: toastHost
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.rightMargin: Theme.space4
        anchors.bottomMargin: Theme.statusBarHeight + Theme.space3
    }

    // ================= destructive-action confirmation =================
    // One instance serves every page; the pending action lives in Python.
    ConfirmDialog {
        id: confirmDialog
        confirm: app.pendingConfirm
        // Visibility is driven by the Connections block below, since the
        // controller owns both the spec and the pending action.
        onConfirmed: app.confirmPending()
        onCancelled: app.cancelPending()
    }

    Connections {
        target: app

        function onConfirmChanged() {
            if (app.confirmOpen) {
                if (!confirmDialog.opened)
                    confirmDialog.open()
            } else if (confirmDialog.opened) {
                confirmDialog.close()
            }
        }
    }

    Connections {
        target: app

        function onToastRequested(message, level, detail) {
            toastHost.push(message, level, detail)
        }

        function onErrorRaised(message) {
            toastHost.push(message, "error", "")
        }
    }
}
