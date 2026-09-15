import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import theme
import components

// 首页: current profile, API health, current project, proxy and recent activity.
Flickable {
    id: page

    contentWidth: width
    contentHeight: content.implicitHeight + Theme.space5 * 2
    clip: true
    boundsBehavior: Flickable.StopAtBounds
    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

    ColumnLayout {
        id: content
        x: Theme.space5
        y: Theme.space5
        width: page.width - Theme.space5 * 2
        spacing: Theme.space4

        SectionHeader {
            title: "首页"
            description: "当前配置、接口健康、当前项目与路由代理的整体状态。"

            AppButton {
                text: "刷新状态"
                iconName: "refresh"
                enabled: !app.busy
                onClicked: dashboardModel.refreshAll()
            }

            AppButton {
                text: "全部检测"
                iconName: "pulse"
                variant: "primary"
                enabled: !app.busy
                onClicked: dashboardModel.runHealthCheckAll()
            }
        }

        GridLayout {
            Layout.fillWidth: true
            columns: page.width > 1100 ? 4 : 2
            columnSpacing: Theme.space3
            rowSpacing: Theme.space3

            Repeater {
                model: dashboardModel.items

                delegate: StatCard {
                    required property var modelData

                    Layout.fillWidth: true
                    label: modelData.label
                    value: modelData.value
                    hint: modelData.hint
                    iconName: modelData.icon
                    tone: modelData.tone

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            if (modelData.key === "profile")
                                app.navigateTo("profiles")
                            else if (modelData.key === "project")
                                app.navigateTo("projects")
                            else if (modelData.key === "proxy")
                                app.navigateTo("network")
                            else
                                app.navigateTo("profiles")
                        }
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space3

            AppCard {
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignTop
                title: "当前 Codex / Claude 配置"
                iconName: "profile"

                DetailRow {
                    label: "当前配置"
                    value: dashboardModel.summary.currentProfileName
                }
                DetailRow {
                    label: "配置健康"
                    value: dashboardModel.summary.currentProfileName === "未选择"
                        ? "未检测"
                        : Theme.healthLabel(dashboardModel.summary.currentProfileHealth)
                    tone: dashboardModel.summary.currentProfileName === "未选择"
                        ? "unknown" : dashboardModel.summary.currentProfileTone
                }
                DetailRow {
                    label: "全局 Codex"
                    value: dashboardModel.summary.codexProfileName
                }
                DetailRow {
                    label: "全局 Claude"
                    value: dashboardModel.summary.claudeProfileName
                }
                DetailRow {
                    label: "配置总数"
                    value: String(dashboardModel.summary.profileCount)
                }
            }

            AppCard {
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignTop
                title: "路由代理状态"
                iconName: "route"

                DetailRow {
                    label: "运行状态"
                    value: dashboardModel.summary.proxyRunning ? "运行中" : "未启动"
                    tone: dashboardModel.summary.proxyRunning ? "success" : "warning"
                }
                DetailRow {
                    label: "监听地址"
                    value: dashboardModel.summary.proxyBaseUrl || "-"
                    selectable: true
                }
                DetailRow {
                    label: "项目路由"
                    value: String(dashboardModel.summary.proxyRuleCount)
                }
                DetailRow {
                    label: "累计 Token"
                    value: String(dashboardModel.summary.proxyTotalTokens)
                }
                DetailRow {
                    label: "今日 Token"
                    value: String(dashboardModel.summary.proxyTodayTokens)
                }

                RowLayout {
                    Layout.fillWidth: true
                    Layout.topMargin: Theme.space1
                    spacing: Theme.space2

                    AppButton {
                        text: dashboardModel.summary.proxyRunning ? "停止代理" : "启动代理"
                        variant: dashboardModel.summary.proxyRunning ? "danger" : "primary"
                        enabled: !app.busy
                        onClicked: dashboardModel.toggleProxy()
                    }

                    AppButton {
                        text: "打开监控"
                        onClicked: app.navigateTo("network")
                    }
                }
            }

            AppCard {
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignTop
                title: "当前项目"
                iconName: "folder"

                DetailRow {
                    label: "项目名称"
                    value: dashboardModel.summary.currentProjectName
                }
                DetailRow {
                    label: "项目目录"
                    value: dashboardModel.summary.currentProjectDir || "-"
                    selectable: true
                    wrap: true
                }
                DetailRow {
                    label: "项目总数"
                    value: String(dashboardModel.summary.projectCount)
                }
                DetailRow {
                    label: "号池渠道"
                    value: dashboardModel.summary.poolNormal + " 正常 · "
                        + dashboardModel.summary.poolFailed + " 异常"
                    tone: dashboardModel.summary.poolFailed > 0 ? "warning" : "success"
                }

                RowLayout {
                    Layout.fillWidth: true
                    Layout.topMargin: Theme.space1
                    spacing: Theme.space2

                    AppButton {
                        text: "项目工作区"
                        variant: "primary"
                        onClicked: app.navigateTo("projects")
                    }
                    AppButton {
                        text: "配置中心"
                        onClicked: app.navigateTo("profiles")
                    }
                }
            }
        }

        AppCard {
            Layout.fillWidth: true
            title: "最近操作"
            subtitle: "来自健康检测、配置切换、路由代理与仓库同步的事件。"
            iconName: "log"

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.space2

                Item { Layout.fillWidth: true }

                AppButton {
                    text: "清空"
                    variant: "ghost"
                    visible: dashboardModel.activity.length > 0
                    onClicked: dashboardModel.clearActivity()
                }
            }

            EmptyState {
                Layout.fillWidth: true
                visible: dashboardModel.activity.length === 0
                iconName: "log"
                title: "暂无操作记录"
                description: "执行健康检测、切换配置或启动代理后，这里会显示最近的操作。"
            }

            Repeater {
                model: dashboardModel.activity

                delegate: ListRow {
                    required property var modelData

                    Layout.fillWidth: true
                    interactive: false
                    iconName: modelData.source === "proxy" ? "route"
                        : modelData.source === "update" ? "refresh" : "pulse"
                    title: modelData.message !== "" ? modelData.message : modelData.source
                    subtitle: modelData.detail
                    badgeText: modelData.level
                    badgeTone: modelData.tone
                    meta: modelData.timestamp
                }
            }
        }
    }
}
