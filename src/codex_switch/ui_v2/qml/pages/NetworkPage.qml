import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import theme
import components

// 网络与监控: route proxy control, request statistics and the event log.
Item {
    id: page

    readonly property var tabKeys: ["proxy", "stats", "logs"]
    readonly property var tabLabels: ["路由代理", "请求统计", "事件日志"]

    property int currentTab: 0

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.space5
        spacing: Theme.space4

        SectionHeader {
            title: "网络与监控"
            description: "路由代理、Token 统计与事件日志。"

            AppButton {
                text: "刷新"
                iconName: "refresh"
                enabled: !app.busy
                onClicked: proxyModel.refreshStatus()
            }
            AppButton {
                text: proxyModel.status.running ? "停止代理" : "启动代理"
                iconName: "route"
                variant: proxyModel.status.running ? "danger" : "primary"
                enabled: !app.busy
                onClicked: proxyModel.toggle()
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

            // ================= proxy control =================
            RowLayout {
                spacing: Theme.space3

                AppCard {
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignTop
                    title: "监听设置"
                    subtitle: "修改后立即生效；代理运行中会重启监听。"
                    iconName: "route"

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.space2

                        Text {
                            text: "监听地址"
                            color: Theme.textMuted
                            font.pixelSize: Theme.fontCaption
                            Layout.preferredWidth: 84
                        }

                        AppTextField {
                            id: hostField
                            Layout.fillWidth: true
                            text: proxyModel.status.host || "127.0.0.1"
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.space2

                        Text {
                            text: "端口"
                            color: Theme.textMuted
                            font.pixelSize: Theme.fontCaption
                            Layout.preferredWidth: 84
                        }

                        AppTextField {
                            id: portField
                            Layout.fillWidth: true
                            text: String(proxyModel.status.port || "")
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.space2

                        Text {
                            text: "上游超时"
                            color: Theme.textMuted
                            font.pixelSize: Theme.fontCaption
                            Layout.preferredWidth: 84
                        }

                        AppTextField {
                            id: timeoutField
                            Layout.fillWidth: true
                            text: String(proxyModel.status.upstreamTimeoutSeconds || "")
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.space2

                        Text {
                            text: "号池策略"
                            color: Theme.textMuted
                            font.pixelSize: Theme.fontCaption
                            Layout.preferredWidth: 84
                        }

                        AppTextField {
                            Layout.fillWidth: true
                            text: proxyModel.status.strategyLabel || ""
                            readOnly: true
                        }
                    }

                    AppButton {
                        Layout.fillWidth: true
                        text: "保存监听设置"
                        variant: "primary"
                        enabled: !app.busy
                        onClicked: proxyModel.submitSettings({
                            "host": hostField.text,
                            "port": portField.text,
                            "upstreamTimeoutSeconds": timeoutField.text
                        })
                    }
                }

                AppCard {
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignTop
                    title: "代理状态"
                    iconName: "pulse"

                    DetailRow {
                        label: "运行状态"
                        value: proxyModel.status.running ? "运行中" : "未启动"
                        tone: proxyModel.status.running ? "success" : "warning"
                    }
                    DetailRow {
                        label: "监听地址"
                        value: proxyModel.status.baseUrl || "-"
                        selectable: true
                    }
                    DetailRow {
                        label: "项目路由"
                        value: String(proxyModel.status.ruleCount || 0)
                    }
                    DetailRow {
                        label: "项目数"
                        value: String(proxyModel.status.projectCount || 0)
                    }
                    DetailRow {
                        label: "累计 Token"
                        value: String(proxyModel.status.totalTokens || 0)
                    }
                    DetailRow {
                        label: "今日 Token"
                        value: String(proxyModel.status.todayTokens || 0)
                    }

                    Text {
                        Layout.fillWidth: true
                        Layout.topMargin: Theme.space1
                        text: "为当前项目启用路由代理后，项目模板会指向本地代理地址。"
                        color: Theme.textFaint
                        font.pixelSize: Theme.fontCaption
                        wrapMode: Text.WordWrap
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.space2

                        AppButton {
                            text: "为当前项目启用"
                            variant: "primary"
                            enabled: !app.busy
                            onClicked: proxyModel.enableForProject()
                        }
                        AppButton {
                            text: "停用"
                            enabled: !app.busy
                            onClicked: proxyModel.disableForProject()
                        }
                    }
                }
            }

            // ================= statistics =================
            ScrollView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                ColumnLayout {
                    width: page.width - Theme.space5 * 2
                    spacing: Theme.space3

                    AppCard {
                        Layout.fillWidth: true
                        title: "按日统计"
                        iconName: "chart"

                        EmptyState {
                            Layout.fillWidth: true
                            visible: proxyModel.dailyUsage.length === 0
                            iconName: "chart"
                            title: "暂无用量数据"
                            description: "通过路由代理发起请求后，这里会显示 Token 用量。"
                        }

                        Repeater {
                            model: proxyModel.dailyUsage

                            delegate: ListRow {
                                required property var modelData

                                Layout.fillWidth: true
                                interactive: false
                                iconName: "chart"
                                title: modelData.label || modelData.key
                                subtitle: "输入 " + modelData.inputTokens + " · 输出 " + modelData.outputTokens
                                badgeText: modelData.totalTokens + " tokens"
                                badgeTone: "accent"
                                meta: modelData.requests + " 次"
                            }
                        }
                    }

                    AppCard {
                        Layout.fillWidth: true
                        title: "按项目统计"
                        iconName: "folder"

                        EmptyState {
                            Layout.fillWidth: true
                            visible: proxyModel.projectUsage.length === 0
                            iconName: "folder"
                            title: "暂无项目用量"
                        }

                        Repeater {
                            model: proxyModel.projectUsage

                            delegate: ListRow {
                                required property var modelData

                                Layout.fillWidth: true
                                interactive: false
                                iconName: "folder"
                                title: modelData.label || modelData.key
                                subtitle: "输入 " + modelData.inputTokens + " · 输出 " + modelData.outputTokens
                                badgeText: modelData.totalTokens + " tokens"
                                badgeTone: "info"
                                meta: modelData.requests + " 次"
                            }
                        }
                    }

                    AppCard {
                        Layout.fillWidth: true
                        title: "按接口统计"
                        iconName: "cube"

                        EmptyState {
                            Layout.fillWidth: true
                            visible: proxyModel.apiUsage.length === 0
                            iconName: "cube"
                            title: "暂无接口用量"
                        }

                        Repeater {
                            model: proxyModel.apiUsage

                            delegate: ListRow {
                                required property var modelData

                                Layout.fillWidth: true
                                interactive: false
                                iconName: "cube"
                                title: modelData.label || modelData.key
                                subtitle: "输入 " + modelData.inputTokens + " · 输出 " + modelData.outputTokens
                                badgeText: modelData.totalTokens + " tokens"
                                badgeTone: "accent"
                                meta: modelData.requests + " 次"
                            }
                        }
                    }
                }
            }

            // ================= event log =================
            AppCard {
                Layout.fillWidth: true
                Layout.fillHeight: true
                title: "事件日志"
                subtitle: proxyModel.events.length + " 条记录"
                iconName: "log"

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.space2

                    SearchField {
                        Layout.fillWidth: true
                        placeholderText: "筛选日志内容"
                        text: proxyModel.eventFilter
                        onTextEdited: proxyModel.setEventFilter(text)
                    }

                    AppButton {
                        text: "清空"
                        variant: "ghost"
                        onClicked: proxyModel.clearEvents()
                    }
                }

                EmptyState {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    visible: proxyModel.events.length === 0
                    iconName: "log"
                    title: "暂无事件"
                    description: "路由代理启动、请求转发和错误都会记录在这里。"
                }

                ListView {
                    id: logList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    visible: proxyModel.events.length > 0
                    model: proxyModel.events
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                    delegate: RowLayout {
                        required property var modelData

                        width: logList.width
                        spacing: Theme.space2

                        Text {
                            text: modelData.timestamp
                            color: Theme.textFaint
                            font.pixelSize: Theme.fontMono
                            font.family: "Consolas, monospace"
                            Layout.preferredWidth: 150
                            elide: Text.ElideRight
                        }

                        StatusBadge {
                            text: modelData.level
                            tone: modelData.tone
                        }

                        Text {
                            Layout.fillWidth: true
                            text: modelData.message
                            color: Theme.text
                            font.pixelSize: Theme.fontCaption
                            elide: Text.ElideRight
                        }

                        Text {
                            text: modelData.detail
                            color: Theme.textFaint
                            font.pixelSize: Theme.fontCaption
                            elide: Text.ElideRight
                            Layout.maximumWidth: 220
                        }
                    }
                }
            }
        }
    }
}
