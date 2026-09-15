import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import theme
import components

// 号池: groups on the left, channels for the selected group on the right.
RowLayout {
    id: panel

    spacing: Theme.space3

    // -- groups --
    Rectangle {
        Layout.preferredWidth: Math.max(260, panel.width * 0.26)
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
                    text: "号池组"
                    color: Theme.text
                    font.pixelSize: Theme.fontSubtitle
                    font.weight: Font.DemiBold
                }

                AppButton {
                    text: "新增"
                    iconName: "plus"
                    variant: "ghost"
                    onClicked: toolsModel.beginCreatePoolGroup()
                }
            }

            Text {
                Layout.fillWidth: true
                text: (toolsModel.accountPool.normalChannels || 0) + " 正常 · "
                    + (toolsModel.accountPool.failedChannels || 0) + " 异常"
                color: Theme.textMuted
                font.pixelSize: Theme.fontCaption
            }

            EmptyState {
                Layout.fillWidth: true
                visible: toolsModel.poolGroups.length === 0
                iconName: "cube"
                title: "暂无号池组"
                description: "号池组用于在多个渠道之间轮询或故障切换。"
                actionText: "新增号池组"
                onActionTriggered: toolsModel.beginCreatePoolGroup()
            }

            ListView {
                id: groupList
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                model: toolsModel.poolGroups
                visible: toolsModel.poolGroups.length > 0
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                delegate: ListRow {
                    required property var modelData

                    width: groupList.width
                    iconName: "cube"
                    title: modelData.name
                    subtitle: modelData.poolType + " · " + modelData.defaultModel
                    badgeText: modelData.channelCount + " 渠道"
                    badgeTone: modelData.failedCount > 0 ? "warning" : "success"
                    selected: modelData.selected
                    onClicked: toolsModel.selectPoolGroup(modelData.id)
                }
            }
        }
    }

    // -- channels --
    AppCard {
        Layout.fillWidth: true
        Layout.fillHeight: true
        title: "号池渠道"
        subtitle: "当前组内渠道状态与检测结果。"
        iconName: "list"

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space2

            AppButton {
                text: "新增渠道"
                iconName: "plus"
                variant: "primary"
                onClicked: toolsModel.beginCreatePoolChannel()
            }

            AppButton {
                text: "全部检测"
                iconName: "pulse"
                enabled: !app.busy && toolsModel.poolChannels.length > 0
                onClicked: toolsModel.testAllPoolChannels()
            }

            Item { Layout.fillWidth: true }
        }

        EmptyState {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: toolsModel.poolChannels.length === 0
            iconName: "list"
            title: "暂无渠道"
            description: "为当前号池组添加渠道，或从配置库同步渠道。"
        }

        ListView {
            id: channelList
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            visible: toolsModel.poolChannels.length > 0
            model: toolsModel.poolChannels
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            delegate: Rectangle {
                id: channelRow

                required property var modelData

                width: channelList.width
                implicitHeight: channelLayout.implicitHeight + Theme.space2 * 2
                radius: Theme.radiusSm
                color: channelHover.containsMouse ? Theme.surfaceHover : "transparent"

                RowLayout {
                    id: channelLayout
                    anchors.fill: parent
                    anchors.margins: Theme.space2
                    spacing: Theme.space2

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 1

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Theme.space2

                            Text {
                                text: channelRow.modelData.name
                                color: Theme.text
                                font.pixelSize: Theme.fontBody
                                font.weight: Font.Medium
                                elide: Text.ElideRight
                            }

                            StatusBadge {
                                text: channelRow.modelData.statusLabel
                                tone: channelRow.modelData.tone
                                showDot: true
                            }

                            StatusBadge {
                                text: channelRow.modelData.sourceType === "profile" ? "配置库" : "临时"
                                tone: "unknown"
                                visible: true
                            }
                        }

                        Text {
                            Layout.fillWidth: true
                            text: channelRow.modelData.baseUrl + " · " + channelRow.modelData.apiKeyMasked
                            color: Theme.textMuted
                            font.pixelSize: Theme.fontCaption
                            elide: Text.ElideRight
                        }

                        Text {
                            Layout.fillWidth: true
                            text: channelRow.modelData.failureReason
                            color: Theme.danger
                            font.pixelSize: Theme.fontCaption
                            elide: Text.ElideRight
                            visible: channelRow.modelData.failureReason !== ""
                        }
                    }

                    AppButton {
                        text: "检测"
                        variant: "ghost"
                        enabled: !app.busy
                        onClicked: toolsModel.testPoolChannel(channelRow.modelData.id)
                    }

                    AppButton {
                        text: "编辑"
                        variant: "ghost"
                        onClicked: toolsModel.beginEditPoolChannel(channelRow.modelData.id)
                    }

                    AppButton {
                        text: "删除"
                        variant: "ghost"
                        visible: channelRow.modelData.sourceType !== "profile"
                        onClicked: app.requestDeletePoolChannel(channelRow.modelData.id)
                    }
                }

                MouseArea {
                    id: channelHover
                    anchors.fill: parent
                    hoverEnabled: true
                    z: -1
                }
            }
        }
    }
}
