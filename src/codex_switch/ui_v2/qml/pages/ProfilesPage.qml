import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import theme
import components

// 配置中心: library, detail, global targets, health checks, model test, account pool.
Item {
    id: page

    readonly property var tabKeys: ["library", "models", "pool"]
    readonly property var tabLabels: ["配置库", "模型测试", "号池"]

    property int currentTab: 0

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.space5
        spacing: Theme.space4

        SectionHeader {
            title: "配置中心"
            description: "配置库、模型测试与号池渠道。"

            AppButton {
                text: "刷新"
                iconName: "refresh"
                enabled: !app.busy
                onClicked: app.refreshAll()
            }
            AppButton {
                text: "全部检测"
                iconName: "pulse"
                enabled: !app.busy && profilesModel.count > 0
                onClicked: profilesModel.runHealthCheckAll()
            }
            AppButton {
                id: signInAllButton
                text: profilesModel.signIn.pending > 0
                    ? "一键签到 (" + profilesModel.signIn.pending + ")"
                    : "一键签到"
                iconName: "check"
                enabled: profilesModel.hasPendingSignIn && !app.busy
                onClicked: profilesModel.signInAll()

                ToolTip.visible: hovered
                ToolTip.delay: 400
                ToolTip.text: profilesModel.signIn.required > 0
                    ? "今日待签到 " + profilesModel.signIn.pending
                        + " 个 · 已签到 " + profilesModel.signIn.signedToday
                        + " 个" + (profilesModel.signIn.missingUrl > 0
                            ? " · " + profilesModel.signIn.missingUrl + " 个缺地址" : "")
                    : "没有需要签到的配置"
            }
            AppButton {
                text: "新增配置"
                iconName: "plus"
                variant: "primary"
                onClicked: profilesModel.beginCreate()
            }
        }

        // Segmented tab switcher
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

            // ================= tab 1: library =================
            RowLayout {
                spacing: Theme.space3

                // -- list --
                Rectangle {
                    Layout.preferredWidth: Math.max(320, page.width * 0.32)
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
                            placeholderText: "搜索名称 / 模型 / 地址"
                            text: profilesModel.filterText
                            onTextEdited: profilesModel.setFilter(text)
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Theme.space2

                            Text {
                                Layout.fillWidth: true
                                text: profilesModel.count + " 套配置"
                                    + (profilesModel.hideErrorProfiles
                                        ? "（已隐藏 " + profilesModel.errorCount + " 个异常）" : "")
                                color: Theme.textFaint
                                font.pixelSize: Theme.fontCaption
                                elide: Text.ElideRight
                            }

                            AppButton {
                                text: profilesModel.hideErrorProfiles ? "显示异常" : "隐藏异常"
                                iconName: profilesModel.hideErrorProfiles ? "restore" : "warning"
                                variant: "ghost"
                                enabled: profilesModel.errorCount > 0 || profilesModel.hideErrorProfiles
                                onClicked: profilesModel.toggleHideErrorProfiles()

                                ToolTip.visible: hovered
                                ToolTip.delay: 400
                                ToolTip.text: profilesModel.errorCount > 0
                                    ? "当前有 " + profilesModel.errorCount + " 个异常配置"
                                    : "当前没有异常配置"
                            }
                        }

                        EmptyState {
                            Layout.fillWidth: true
                            visible: profilesModel.count === 0
                            iconName: "profile"
                            title: profilesModel.filterText !== "" ? "没有匹配的配置" : "还没有配置"
                            description: profilesModel.filterText !== ""
                                ? "换个关键词，或清空搜索条件。"
                                : "新增一套 API 配置后即可切换使用。"
                            actionText: profilesModel.filterText !== "" ? "清空搜索" : "新增配置"
                            onActionTriggered: {
                                if (profilesModel.filterText !== "")
                                    profilesModel.clearFilter()
                                else
                                    profilesModel.beginCreate()
                            }
                        }

                        ListView {
                            id: profileList
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            model: profilesModel.items
                            boundsBehavior: Flickable.StopAtBounds
                            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                            visible: profilesModel.count > 0

                            delegate: ListRow {
                                required property var modelData

                                width: profileList.width
                                // The icon carries sign-in state so the health badge
                                // stays visible instead of being replaced.
                                iconName: modelData.requiresSignIn && !modelData.signedToday
                                    ? "warning"
                                    : modelData.requiresSignIn ? "check" : "profile"
                                title: modelData.name
                                subtitle: modelData.baseUrl
                                badgeText: modelData.healthLabel
                                badgeTone: modelData.healthTone
                                meta: modelData.requiresSignIn && !modelData.signedToday
                                    ? modelData.vendorLabel + " · 待签到"
                                    : modelData.vendorLabel
                                // Compare against the model's selection so the
                                // row list itself never carries selection
                                // state; rebuilding it would reset the scroll.
                                selected: profilesModel.selectedId === modelData.id
                                onClicked: profilesModel.select(modelData.id)

                                ToolTip.visible: hovered
                                ToolTip.delay: 700
                                ToolTip.text: modelData.model + " · " + modelData.apiKeyMasked
                            }
                        }
                    }
                }

                // -- detail --
                ScrollView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                    ColumnLayout {
                        width: page.width - Math.max(320, page.width * 0.32) - Theme.space5 * 2 - Theme.space3
                        spacing: Theme.space3

                        EmptyState {
                            Layout.fillWidth: true
                            Layout.topMargin: Theme.space6
                            visible: !profilesModel.hasSelection
                            iconName: "profile"
                            title: "未选择配置"
                            description: "在左侧选择一套配置查看详情，或新增一套配置。"
                        }

                        AppCard {
                            Layout.fillWidth: true
                            visible: profilesModel.hasSelection
                            title: profilesModel.selectedDetail.name || ""
                            subtitle: profilesModel.selectedDetail.baseUrl || ""
                            iconName: "profile"

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: Theme.space1 + 2

                                StatusBadge {
                                    text: profilesModel.selectedDetail.healthLabel || "未检测"
                                    tone: profilesModel.selectedDetail.healthTone || "unknown"
                                    showDot: true
                                }
                                StatusBadge {
                                    text: profilesModel.selectedDetail.vendorLabel || "-"
                                    tone: "info"
                                }
                                StatusBadge {
                                    text: profilesModel.selectedDetail.categoryLabel || "-"
                                    tone: "unknown"
                                }
                                Item { Layout.fillWidth: true }
                            }

                            DetailRow { label: "Provider"; value: profilesModel.selectedDetail.providerName || "-" }
                            DetailRow { label: "接口标准"; value: profilesModel.selectedDetail.wireApi || "-" }
                            DetailRow { label: "Codex 模型"; value: profilesModel.selectedDetail.codexModel || "-" }
                            DetailRow { label: "Claude 模型"; value: profilesModel.selectedDetail.claudeModel || "-" }
                            DetailRow {
                                label: "Claude 兜底"
                                value: profilesModel.selectedDetail.claudeFallbackModel || "-"
                            }
                            DetailRow {
                                label: "API Key"
                                value: profilesModel.selectedDetail.apiKeyMasked || "-"
                            }
                            DetailRow {
                                label: "Key 数量"
                                value: String(profilesModel.selectedDetail.apiKeyCount || 0)
                            }
                            DetailRow {
                                label: "检测时间"
                                value: profilesModel.selectedDetail.healthCheckedAt || "尚未检测"
                            }
                            DetailRow {
                                label: "签到状态"
                                value: {
                                    var status = profilesModel.selectedDetail.signInStatus || "-"
                                    var last = profilesModel.selectedDetail.lastSignedDate
                                    return last ? (status + "（上次 " + last + "）") : status
                                }
                                tone: profilesModel.selectedDetail.signedToday === true ? "success" : "warning"
                                visible: profilesModel.selectedDetail.requiresSignIn === true
                            }
                            DetailRow {
                                label: "检测详情"
                                value: profilesModel.selectedDetail.healthDetail || "-"
                                tone: profilesModel.selectedDetail.healthTone || "unknown"
                                wrap: true
                            }

                            // Manual status: health checks only measure
                            // connectivity, so allow pinning a status by hand.
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: Theme.space2

                                Text {
                                    text: "手动状态"
                                    color: Theme.textMuted
                                    font.pixelSize: Theme.fontCaption
                                    Layout.preferredWidth: 104
                                }

                                AppComboBox {
                                    Layout.fillWidth: true
                                    options: profilesModel.manualStatusChoices
                                    selectedValue: profilesModel.selectedDetail.manualHealthStatus || ""
                                    onSelectionChanged: function (value) {
                                        profilesModel.setManualHealthStatus(value)
                                    }
                                }
                            }

                            Text {
                                Layout.fillWidth: true
                                text: profilesModel.selectedDetail.manualHealthStatus
                                    ? "当前以手动状态为准，自动检测结果仅作参考。"
                                    : "当前使用自动检测结果；异常时可在此手动修正。"
                                color: Theme.textFaint
                                font.pixelSize: Theme.fontCaption
                                wrapMode: Text.WordWrap
                            }

                            DetailRow {
                                label: "备注"
                                value: profilesModel.selectedDetail.notes || "-"
                                wrap: true
                            }

                            Flow {
                                Layout.fillWidth: true
                                Layout.topMargin: Theme.space1
                                spacing: Theme.space2

                                AppButton {
                                    text: "应用为当前配置"
                                    variant: "primary"
                                    enabled: !app.busy
                                    onClicked: profilesModel.applySelected()
                                }
                                AppButton {
                                    text: "健康检测"
                                    iconName: "pulse"
                                    enabled: !app.busy
                                    onClicked: profilesModel.runHealthCheck(profilesModel.selectedId)
                                }
                                AppButton {
                                    text: "编辑"
                                    onClicked: profilesModel.beginEdit(profilesModel.selectedId)
                                }
                                AppButton {
                                    text: "打开签到"
                                    visible: profilesModel.selectedDetail.requiresSignIn === true
                                    onClicked: profilesModel.openSignIn(profilesModel.selectedId)
                                }
                                AppButton {
                                    text: profilesModel.selectedDetail.signedToday === true
                                        ? "已签到（今日）" : "标记已签到"
                                    visible: profilesModel.selectedDetail.requiresSignIn === true
                                    enabled: profilesModel.selectedDetail.signedToday !== true
                                    onClicked: profilesModel.markSignedIn(profilesModel.selectedId)
                                }
                                AppButton {
                                    text: "删除"
                                    variant: "danger"
                                    onClicked: app.requestDeleteProfile(profilesModel.selectedId)
                                }
                            }
                        }

                    }
                }
            }

            // ================= tab 2: model test =================
            ModelTestPanel {
                Layout.fillWidth: true
                Layout.fillHeight: true
            }

            // ================= tab 3: account pool =================
            AccountPoolPanel {
                Layout.fillWidth: true
                Layout.fillHeight: true
            }
        }
    }
}
