import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import theme
import components

// 项目工作区: projects + templates, MCP and Skills.
Item {
    id: page

    readonly property var tabKeys: ["projects", "mcp", "skills"]
    readonly property var tabLabels: ["项目列表", "MCP", "Skills"]

    property int currentTab: 0

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.space5
        spacing: Theme.space4

        SectionHeader {
            title: "项目工作区"
            description: "项目绑定、模板生成、MCP 与 Skills 管理。"

            AppButton {
                text: "刷新"
                iconName: "refresh"
                enabled: !app.busy
                onClicked: app.refreshAll()
            }
            AppButton {
                text: "新增项目"
                iconName: "plus"
                variant: "primary"
                onClicked: projectsModel.beginCreate()
            }
        }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: Theme.controlHeight + Theme.space1 * 2
            radius: Theme.radiusSm
            color: Theme.surfaceAlt

            RowLayout {
                anchors.fill: parent
                anchors.margins: Theme.space1
                spacing: Theme.space1

                Repeater {
                    model: page.tabKeys

                    delegate: Rectangle {
                        id: tabButton

                        required property int index
                        required property string modelData

                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        radius: Theme.radiusSm - 2
                        color: page.currentTab === tabButton.index ? Theme.surface : "transparent"
                        border.width: page.currentTab === tabButton.index ? Theme.borderWidth : 0
                        border.color: Theme.border

                        Text {
                            anchors.centerIn: parent
                            text: page.tabLabels[tabButton.index]
                            color: page.currentTab === tabButton.index ? Theme.text : Theme.textMuted
                            font.pixelSize: Theme.fontBody
                            font.weight: page.currentTab === tabButton.index ? Font.DemiBold : Font.Normal
                        }

                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: page.currentTab = tabButton.index
                        }
                    }
                }
            }
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: page.currentTab

            // ================= projects =================
            RowLayout {
                spacing: Theme.space3

                Rectangle {
                    Layout.preferredWidth: Math.max(300, page.width * 0.3)
                    Layout.fillHeight: true
                    radius: Theme.radius
                    color: Theme.surface
                    border.width: Theme.borderWidth
                    border.color: Theme.border

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: Theme.space3
                        spacing: Theme.space2

                        SearchField {
                            Layout.fillWidth: true
                            placeholderText: "搜索项目名称 / 目录"
                            text: projectsModel.filterText
                            onTextEdited: projectsModel.setFilter(text)
                        }

                        Text {
                            Layout.fillWidth: true
                            text: projectsModel.count + " 个项目"
                            color: Theme.textFaint
                            font.pixelSize: Theme.fontCaption
                        }

                        EmptyState {
                            Layout.fillWidth: true
                            visible: projectsModel.count === 0
                            iconName: "folder"
                            title: projectsModel.filterText !== "" ? "没有匹配的项目" : "还没有项目"
                            description: projectsModel.filterText !== ""
                                ? "换个关键词，或清空搜索条件。"
                                : "新增一个项目后即可生成模板并启动。"
                            actionText: projectsModel.filterText !== "" ? "清空搜索" : "新增项目"
                            onActionTriggered: {
                                if (projectsModel.filterText !== "")
                                    projectsModel.clearFilter()
                                else
                                    projectsModel.beginCreate()
                            }
                        }

                        ListView {
                            id: projectList
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            model: projectsModel.items
                            visible: projectsModel.count > 0
                            boundsBehavior: Flickable.StopAtBounds
                            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                            delegate: ListRow {
                                required property var modelData

                                width: projectList.width
                                iconName: "folder"
                                title: modelData.name
                                subtitle: modelData.projectDir
                                badgeText: modelData.githubRepo !== "" ? "GIT" : ""
                                badgeTone: "info"
                                meta: modelData.skillCount + " Skills"
                                selected: projectsModel.selectedId === modelData.id
                                onClicked: projectsModel.select(modelData.id)
                            }
                        }
                    }
                }

                ScrollView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                    ColumnLayout {
                        width: page.width - Math.max(300, page.width * 0.3) - Theme.space5 * 2 - Theme.space3
                        spacing: Theme.space3

                        EmptyState {
                            Layout.fillWidth: true
                            Layout.topMargin: Theme.space6
                            visible: !projectsModel.hasSelection
                            iconName: "folder"
                            title: "未选择项目"
                            description: "在左侧选择一个项目查看详情。"
                        }

                        AppCard {
                            Layout.fillWidth: true
                            visible: projectsModel.hasSelection
                            title: projectsModel.selectedDetail.name || ""
                            subtitle: projectsModel.selectedDetail.projectDir || ""
                            iconName: "folder"

                            DetailRow {
                                label: "Codex 配置"
                                value: projectsModel.selectedDetail.codexProfileName || "未绑定"
                            }
                            DetailRow {
                                label: "Codex 模型"
                                value: projectsModel.selectedDetail.codexModel || "-"
                            }
                            DetailRow {
                                label: "Claude 配置"
                                value: projectsModel.selectedDetail.claudeProfileName || "未绑定"
                            }
                            DetailRow {
                                label: "Claude 模型"
                                value: projectsModel.selectedDetail.claudeModel || "-"
                            }
                            DetailRow {
                                label: "运行命令"
                                value: projectsModel.selectedDetail.runCommand || "未配置"
                                selectable: true
                            }
                            DetailRow { label: "MCP"; value: projectsModel.selectedDetail.mcpText || "未选择" }
                            DetailRow { label: "Skills"; value: projectsModel.selectedDetail.skillsText || "未选择" }
                            DetailRow {
                                label: "GitHub"
                                value: projectsModel.selectedDetail.githubText || "未配置"
                                selectable: true
                                wrap: true
                            }

                            Flow {
                                Layout.fillWidth: true
                                Layout.topMargin: Theme.space1
                                spacing: Theme.space2

                                AppButton {
                                    text: "生成 Codex 模板"
                                    variant: "primary"
                                    enabled: !app.busy
                                    onClicked: projectsModel.generateCodexTemplate()
                                }
                                AppButton {
                                    text: "生成 Claude 模板"
                                    enabled: !app.busy
                                    onClicked: projectsModel.generateClaudeTemplate()
                                }
                                AppButton {
                                    text: "同步绑定"
                                    enabled: !app.busy
                                    onClicked: projectsModel.syncBinding()
                                }
                                AppButton {
                                    text: "编辑"
                                    onClicked: projectsModel.beginEdit(projectsModel.selectedId)
                                }
                                AppButton {
                                    text: "删除"
                                    variant: "danger"
                                    onClicked: app.requestDeleteProject(projectsModel.selectedId)
                                }
                            }

                            Text {
                                Layout.fillWidth: true
                                Layout.topMargin: Theme.space2
                                text: "启动方式"
                                color: Theme.textMuted
                                font.pixelSize: Theme.fontCaption
                            }

                            Flow {
                                Layout.fillWidth: true
                                spacing: Theme.space2

                                AppButton {
                                    text: "打开目录"
                                    iconName: "folder"
                                    onClicked: projectsModel.openFolder()
                                }
                                AppButton {
                                    text: "VS Code"
                                    iconName: "terminal"
                                    onClicked: projectsModel.openVsCode()
                                }
                                AppButton {
                                    text: "运行项目"
                                    iconName: "terminal"
                                    onClicked: projectsModel.runProject()
                                }
                                AppButton {
                                    text: "Codex CMD"
                                    iconName: "terminal"
                                    onClicked: projectsModel.openCodexCmd()
                                }
                                AppButton {
                                    text: "Claude CMD"
                                    iconName: "terminal"
                                    onClicked: projectsModel.openClaudeCmd()
                                }
                                AppButton {
                                    text: "同步仓库"
                                    iconName: "download"
                                    enabled: !app.busy
                                    visible: projectsModel.selectedDetail.hasGithub === true
                                    onClicked: projectsModel.syncRepo()
                                }
                            }
                        }
                    }
                }
            }

            // ================= MCP =================
            RowLayout {
                spacing: Theme.space3

                Rectangle {
                    Layout.preferredWidth: Math.max(300, page.width * 0.3)
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
                                text: "MCP 服务"
                                color: Theme.text
                                font.pixelSize: Theme.fontSubtitle
                                font.weight: Font.DemiBold
                            }

                            AppButton {
                                text: "新增"
                                iconName: "plus"
                                variant: "ghost"
                                onClicked: toolsModel.beginCreateMcp()
                            }
                        }

                        EmptyState {
                            Layout.fillWidth: true
                            visible: toolsModel.mcpServers.length === 0
                            iconName: "cube"
                            title: "暂无 MCP 服务"
                            description: "新增服务，或恢复默认配置。"
                            actionText: "恢复默认"
                            onActionTriggered: toolsModel.restoreDefaultMcp()
                        }

                        ListView {
                            id: mcpList
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            model: toolsModel.mcpServers
                            visible: toolsModel.mcpServers.length > 0
                            boundsBehavior: Flickable.StopAtBounds
                            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                            delegate: ListRow {
                                required property var modelData

                                width: mcpList.width
                                iconName: "cube"
                                title: modelData.name
                                subtitle: modelData.command
                                badgeText: modelData.type
                                badgeTone: "info"
                                meta: modelData.argsCount + " args"
                                // Reflect the current selection, which also
                                // drives the preview panel on the right.
                                selected: toolsModel.selectedMcpName === modelData.name
                                onClicked: toolsModel.selectMcpServer(modelData.name)
                            }
                        }

                        AppButton {
                            Layout.fillWidth: true
                            text: "恢复默认 MCP 配置"
                            iconName: "restore"
                            visible: toolsModel.mcpServers.length > 0
                            onClicked: toolsModel.restoreDefaultMcp()
                        }
                    }
                }

                AppCard {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    title: "MCP 配置预览"
                    subtitle: toolsModel.mcpDetail.summary || "选择一个 MCP 服务查看配置。"
                    iconName: "file"

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.space2

                        // Act on the SELECTED server; previously these always
                        // targeted servers[0], so 删除 could remove the wrong one.
                        AppButton {
                            text: "编辑"
                            enabled: toolsModel.selectedMcpName !== ""
                            onClicked: toolsModel.beginEditMcp(toolsModel.selectedMcpName)
                        }
                        AppButton {
                            text: "删除"
                            variant: "danger"
                            enabled: toolsModel.selectedMcpName !== ""
                            onClicked: app.requestDeleteMcpServer(toolsModel.selectedMcpName)
                        }
                        Item { Layout.fillWidth: true }
                    }

                    ScrollView {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true

                        Text {
                            text: toolsModel.mcpDetail.preview || "（无配置）"
                            color: Theme.text
                            font.pixelSize: Theme.fontMono
                            font.family: "Consolas, monospace"
                            wrapMode: Text.WrapAnywhere
                            textFormat: Text.PlainText
                            padding: Theme.space2
                        }
                    }
                }
            }

            // ================= Skills =================
            RowLayout {
                spacing: Theme.space3

                AppCard {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    title: "Skills 组"
                    subtitle: "按组管理 Skill，并同步到项目。"
                    iconName: "tag"

                    AppButton {
                        Layout.fillWidth: true
                        text: "新增 Skills 组"
                        iconName: "plus"
                        variant: "primary"
                        onClicked: toolsModel.beginCreateSkillGroup()
                    }

                    EmptyState {
                        Layout.fillWidth: true
                        visible: toolsModel.skillGroups.length === 0
                        iconName: "tag"
                        title: "暂无 Skills 组"
                        description: "创建组后即可添加 Skill 或从仓库安装。"
                    }

                    ListView {
                        id: skillGroupList
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        model: toolsModel.skillGroups
                        visible: toolsModel.skillGroups.length > 0
                        boundsBehavior: Flickable.StopAtBounds
                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                        delegate: Column {
                            id: skillGroupRow

                            required property var modelData

                            width: skillGroupList.width
                            spacing: Theme.space1

                            // The group header owns the hover highlight. It must
                            // NOT span the skill rows below it, otherwise moving
                            // the mouse over any skill lights up the whole group.
                            Rectangle {
                                id: skillGroupHeader

                                width: parent.width
                                implicitHeight: headerColumn.implicitHeight + Theme.space2 * 2
                                radius: Theme.radiusSm
                                color: "transparent"

                                Rectangle {
                                    anchors.fill: parent
                                    radius: parent.radius
                                    color: Theme.surfaceHover
                                    opacity: headerHover.containsMouse ? 1 : 0

                                    Behavior on opacity {
                                        NumberAnimation {
                                            duration: Theme.durationFast
                                            easing.type: Easing.OutCubic
                                        }
                                    }
                                }

                                ColumnLayout {
                                    id: headerColumn
                                    anchors.fill: parent
                                    anchors.margins: Theme.space2
                                    spacing: Theme.space1

                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: Theme.space2

                                        Text {
                                            Layout.fillWidth: true
                                            text: skillGroupRow.modelData.name
                                            color: Theme.text
                                            font.pixelSize: Theme.fontBody
                                            font.weight: Font.Medium
                                            elide: Text.ElideRight
                                        }

                                        StatusBadge {
                                            text: skillGroupRow.modelData.skillCount + " 个"
                                            tone: "info"
                                        }

                                        AppButton {
                                            text: "加 Skill"
                                            variant: "ghost"
                                            onClicked: toolsModel.beginCreateSkill(skillGroupRow.modelData.id)
                                        }
                                        AppButton {
                                            text: "编辑"
                                            variant: "ghost"
                                            onClicked: toolsModel.beginEditSkillGroup(skillGroupRow.modelData.id)
                                        }
                                        AppButton {
                                            text: "删除"
                                            variant: "ghost"
                                            onClicked: app.requestDeleteSkillGroup(skillGroupRow.modelData.id)
                                        }
                                    }

                                    Text {
                                        Layout.fillWidth: true
                                        text: skillGroupRow.modelData.description
                                        color: Theme.textMuted
                                        font.pixelSize: Theme.fontCaption
                                        elide: Text.ElideRight
                                        visible: skillGroupRow.modelData.description !== ""
                                    }
                                }

                                MouseArea {
                                    id: headerHover
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    z: -1
                                }
                            }

                            // Each skill row highlights on its own, so hovering one
                            // skill no longer dims the entire group.
                            Repeater {
                                model: skillGroupRow.modelData.skills || []

                                delegate: Rectangle {
                                    id: skillRow

                                    required property var modelData

                                    width: skillGroupRow.width
                                    implicitHeight: skillRowLayout.implicitHeight + Theme.space1 * 2
                                    radius: Theme.radiusSm
                                    color: "transparent"

                                    Rectangle {
                                        anchors.fill: parent
                                        radius: parent.radius
                                        color: Theme.surfaceHover
                                        opacity: skillRowHover.containsMouse ? 1 : 0

                                        Behavior on opacity {
                                            NumberAnimation {
                                                duration: Theme.durationFast
                                                easing.type: Easing.OutCubic
                                            }
                                        }
                                    }

                                    RowLayout {
                                        id: skillRowLayout
                                        anchors.fill: parent
                                        anchors.leftMargin: Theme.space2 + Theme.space2
                                        anchors.rightMargin: Theme.space2
                                        spacing: Theme.space2

                                        AppIcon { name: "file"; color: Theme.textFaint; size: 13 }

                                        Text {
                                            Layout.fillWidth: true
                                            text: skillRow.modelData.name + "  ·  " + skillRow.modelData.type
                                            color: Theme.textMuted
                                            font.pixelSize: Theme.fontCaption
                                            elide: Text.ElideRight
                                        }

                                        AppButton {
                                            text: "编辑"
                                            variant: "ghost"
                                            onClicked: toolsModel.beginEditSkill(
                                                skillGroupRow.modelData.id, skillRow.modelData.id)
                                        }
                                        AppButton {
                                            text: "删除"
                                            variant: "ghost"
                                            onClicked: app.requestDeleteSkill(
                                                skillGroupRow.modelData.id, skillRow.modelData.id)
                                        }
                                    }

                                    MouseArea {
                                        id: skillRowHover
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        z: -1
                                    }
                                }
                            }
                        }
                    }
                }

                AppCard {
                    Layout.preferredWidth: Math.max(300, page.width * 0.3)
                    Layout.fillHeight: true
                    title: "Skills 仓库"
                    subtitle: "从 GitHub 仓库安装 Skills。"
                    iconName: "download"

                    AppButton {
                        Layout.fillWidth: true
                        text: "新增仓库"
                        iconName: "plus"
                        onClicked: toolsModel.beginCreateSkillRepo()
                    }

                    EmptyState {
                        Layout.fillWidth: true
                        visible: toolsModel.skillRepos.length === 0
                        iconName: "download"
                        title: "暂无仓库"
                        description: "添加一个 GitHub 仓库以安装其中的 Skills。"
                    }

                    ListView {
                        id: skillRepoList
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        model: toolsModel.skillRepos
                        visible: toolsModel.skillRepos.length > 0
                        boundsBehavior: Flickable.StopAtBounds
                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                        delegate: ColumnLayout {
                            required property var modelData

                            width: skillRepoList.width
                            spacing: Theme.space1

                            ListRow {
                                Layout.fillWidth: true
                                iconName: "download"
                                title: modelData.url
                                subtitle: modelData.branch + " · " + modelData.lastSyncCommit
                                badgeText: modelData.installed ? "已安装" : "未安装"
                                badgeTone: modelData.installed ? "success" : "unknown"
                                interactive: false
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                Layout.leftMargin: Theme.space2
                                spacing: Theme.space2

                                AppButton {
                                    text: "安装"
                                    enabled: !app.busy
                                    onClicked: toolsModel.installSkillRepo(modelData.id)
                                }
                                AppButton {
                                    text: "编辑"
                                    variant: "ghost"
                                    onClicked: toolsModel.beginEditSkillRepo(modelData.id)
                                }
                                AppButton {
                                    text: "删除"
                                    variant: "ghost"
                                    onClicked: app.requestDeleteSkillRepo(modelData.id)
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
