import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import theme
import components

// 系统: document template, updates and settings.
Item {
    id: page

    readonly property var tabKeys: ["general", "docs", "updates"]
    readonly property var tabLabels: ["设置", "文档模板", "自动更新"]

    property int currentTab: 0

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.space5
        spacing: Theme.space4

        SectionHeader {
            title: "系统"
            description: "主题、文档模板、自动更新与运行环境。"

            AppButton {
                text: "刷新"
                iconName: "refresh"
                enabled: !app.busy
                onClicked: app.refreshAll()
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

            // ================= general =================
            ScrollView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                RowLayout {
                    width: page.width - Theme.space5 * 2
                    spacing: Theme.space3

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: Theme.space3

                        AppCard {
                            Layout.fillWidth: true
                            title: "外观"
                            iconName: "settings"

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: Theme.space3

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 2

                                    Text {
                                        text: "深色主题"
                                        color: Theme.text
                                        font.pixelSize: Theme.fontBody
                                    }
                                    Text {
                                        text: "当前：" + settingsModel.summary.themeLabel
                                        color: Theme.textMuted
                                        font.pixelSize: Theme.fontCaption
                                    }
                                }

                                AppSwitch {
                                    checked: settingsModel.darkMode
                                    onToggled: settingsModel.setDarkMode(checked)
                                }
                            }
                        }

                        AppCard {
                            Layout.fillWidth: true
                            title: "仓库自动同步"
                            iconName: "refresh"

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: Theme.space3

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 2

                                    Text {
                                        text: "启用自动同步"
                                        color: Theme.text
                                        font.pixelSize: Theme.fontBody
                                    }
                                    Text {
                                        text: "自动更新标记了自动更新的 Skills 仓库与项目。"
                                        color: Theme.textMuted
                                        font.pixelSize: Theme.fontCaption
                                        wrapMode: Text.WordWrap
                                    }
                                }

                                AppSwitch {
                                    id: hotUpdateSwitch
                                    checked: settingsModel.summary.hotUpdateEnabled === true
                                }
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: Theme.space2

                                Text {
                                    text: "检查间隔（分钟）"
                                    color: Theme.textMuted
                                    font.pixelSize: Theme.fontCaption
                                    Layout.preferredWidth: 140
                                }

                                AppTextField {
                                    id: intervalField
                                    Layout.fillWidth: true
                                    text: String(settingsModel.summary.hotUpdateIntervalMinutes || 30)
                                }
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: Theme.space2

                                Text {
                                    text: "模型测试并发"
                                    color: Theme.textMuted
                                    font.pixelSize: Theme.fontCaption
                                    Layout.preferredWidth: 140
                                }

                                AppTextField {
                                    id: concurrencyField
                                    Layout.fillWidth: true
                                    text: String(settingsModel.summary.modelBatchConcurrency || 3)
                                }
                            }

                            AppButton {
                                Layout.fillWidth: true
                                text: "保存设置"
                                variant: "primary"
                                enabled: !app.busy
                                onClicked: settingsModel.saveGeneral({
                                    "hotUpdateEnabled": hotUpdateSwitch.checked,
                                    "hotUpdateIntervalMinutes": intervalField.text,
                                    "modelBatchConcurrency": concurrencyField.text
                                })
                            }
                        }
                    }

                    AppCard {
                        Layout.preferredWidth: 380
                        Layout.alignment: Qt.AlignTop
                        title: "运行环境"
                        iconName: "cube"

                        DetailRow { label: "版本"; value: app.version }
                        DetailRow { label: "Python"; value: settingsModel.summary.python || "-" }
                        DetailRow { label: "Qt"; value: settingsModel.summary.qt || "-" }
                        DetailRow {
                            label: "配置数量"
                            value: String(settingsModel.summary.profileCount || 0)
                        }
                        DetailRow {
                            label: "项目数量"
                            value: String(settingsModel.summary.projectCount || 0)
                        }
                        DetailRow {
                            label: "数据目录"
                            value: settingsModel.summary.storagePath || "-"
                            selectable: true
                            wrap: true
                        }

                        AppButton {
                            Layout.fillWidth: true
                            text: "打开数据目录"
                            iconName: "folder"
                            enabled: (settingsModel.summary.storagePath || "") !== ""
                            onClicked: settingsModel.openPath(settingsModel.summary.storagePath)
                        }
                    }
                }
            }

            // ================= document template =================
            AppCard {
                Layout.fillWidth: true
                Layout.fillHeight: true
                title: "AGENTS.md 文档模板"
                subtitle: "生成项目模板时写入的默认文档内容。"
                iconName: "file"

                AppTextArea {
                    id: docsArea
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    text: settingsModel.agentsDocText
                    wrapMode: TextArea.Wrap
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.space2

                    Item { Layout.fillWidth: true }

                    AppButton {
                        text: "恢复默认"
                        iconName: "restore"
                        onClicked: settingsModel.restoreAgentsDoc()
                    }

                    AppButton {
                        text: "保存"
                        variant: "primary"
                        enabled: !app.busy
                        onClicked: settingsModel.saveAgentsDoc(docsArea.text)
                    }
                }
            }

            // ================= updates =================
            RowLayout {
                spacing: Theme.space3

                AppCard {
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignTop
                    title: "软件更新"
                    subtitle: "检查 GitHub Releases 上的新版本。"
                    iconName: "download"

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.space2

                        StatusBadge {
                            text: settingsModel.updateState.checked
                                ? (settingsModel.updateState.updateAvailable ? "有新版本" : "已是最新")
                                : "尚未检查"
                            tone: settingsModel.updateState.checked
                                ? (settingsModel.updateState.updateAvailable ? "warning" : "success")
                                : "unknown"
                            showDot: true
                        }
                        Item { Layout.fillWidth: true }
                    }

                    DetailRow {
                        label: "最新版本"
                        value: settingsModel.updateState.version || "-"
                    }

                    AppButton {
                        Layout.fillWidth: true
                        text: "检查更新"
                        iconName: "refresh"
                        variant: "primary"
                        enabled: !app.busy
                        onClicked: settingsModel.checkSoftwareUpdate()
                    }
                }

                AppCard {
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignTop
                    title: "仓库同步"
                    subtitle: "检查 Skills 仓库与项目的远端更新。"
                    iconName: "refresh"

                    Text {
                        Layout.fillWidth: true
                        text: "共 " + (settingsModel.summary.hotUpdateEventCount || 0) + " 条同步事件记录。"
                        color: Theme.textMuted
                        font.pixelSize: Theme.fontCaption
                    }

                    AppButton {
                        Layout.fillWidth: true
                        text: "立即检查"
                        iconName: "refresh"
                        variant: "primary"
                        enabled: !app.busy
                        onClicked: settingsModel.checkHotUpdates()
                    }
                }
            }
        }
    }
}
